"""Вызов модели. Асинхронный, с повторами и потолком на одновременные запросы."""

import asyncio
import os
import random
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime

import httpx

from core.providers import ANTHROPIC, ProviderError, for_model

# Оставлено для совместимости: раньше клиент знал только Anthropic
API_URL = ANTHROPIC.url
API_VERSION = ANTHROPIC.version

# Коды, после которых есть смысл повторить: слишком часто, перегрузка, сбой сервера.
# 400 или 401 повторять бессмысленно: запрос не станет верным от повтора.
RETRY_CODES = {429, 500, 502, 503, 529}

# Потолок длины ответа у Anthropic. У каждого поставщика свой (core.providers),
# и кэш учитывает его в ключе.
MAX_TOKENS = ANTHROPIC.max_tokens

# Дольше этого не ждём по retry-after за один раз, даже если сервер просит больше
MAX_RETRY_AFTER = 90.0


class ModelError(RuntimeError):
    """Модель не ответила и повторять бесполезно."""


@dataclass
class Answer:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    attempts: int
    # Сколько секунд занял вопрос целиком, вместе с паузами между повторами
    seconds: float = 0.0
    # Ответ взят из кэша, а не получен сейчас: за него в этом прогоне не платили
    cached: bool = False
    # Сколько входных токенов поставщик прочитал из своего кэша промпта (у Groq
    # это бывает само, без настройки). Входят отдельно от input_tokens и стоят дешевле.
    cache_read_tokens: int = 0


def backoff_delay(attempt: int, base: float = 1.0, cap: float = 30.0) -> float:
    """Пауза перед следующей попыткой: удваивается, но с разбросом.

    Разброс нужен, чтобы десяток параллельных запросов, получив отказ
    одновременно, не пошёл повторять тоже одновременно и снова не положил
    сервер. Без него повторы сбиваются в волны.
    """
    return min(cap, base * 2 ** attempt) * (0.5 + random.random() / 2)


def retry_after(response: httpx.Response) -> float | None:
    """Сколько секунд просит подождать сервер в заголовке retry-after.

    Бывает число секунд или дата. Если заголовка нет или он непонятный, None:
    тогда пауза считается как обычно, с удвоением.
    """
    value = response.headers.get("retry-after")
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = parsedate_to_datetime(value).timestamp() - time.time()
        except (TypeError, ValueError):
            return None
    if seconds != seconds or seconds < 0:  # NaN или прошлое
        return 0.0
    return min(seconds, MAX_RETRY_AFTER)


async def pause(seconds: float) -> None:
    """Все паузы клиента идут через эту функцию: в тестах её подменяют, чтобы не ждать."""
    await asyncio.sleep(seconds)


class RateLimiter:
    """Не больше per_minute запросов в минуту: запросы стартуют с равным шагом.

    Нужен для бесплатного уровня Groq: лучше идти медленно, чем получать 429
    и тратить попытки. Повторы тоже проходят через ограничитель.
    """

    def __init__(self, per_minute: float, clock=time.monotonic, sleep=None):
        if per_minute <= 0:
            raise ValueError("запросов в минуту должно быть больше нуля")
        self.step = 60.0 / per_minute
        self.clock = clock
        self.sleep = sleep
        self._next = None
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = self.clock()
            start = now if self._next is None else max(now, self._next)
            self._next = start + self.step
        if start > now:
            await (self.sleep or pause)(start - now)


async def ask(
    client: httpx.AsyncClient,
    prompt: str,
    user_input: str,
    model: str,
    max_attempts: int | None = None,
    max_tokens: int | None = None,
    provider=None,
    limiter: RateLimiter | None = None,
) -> Answer:
    """Один вопрос к модели. Повторяет только то, что имеет шанс пройти.

    provider по умолчанию выбирается по имени модели (core.providers.for_model).
    """
    provider = provider or for_model(model)
    max_attempts = max_attempts or provider.max_attempts
    max_tokens = max_tokens or provider.max_tokens

    key = os.environ.get(provider.key_env)
    if not key:
        raise ModelError(f"Не задана переменная окружения {provider.key_env}")

    headers, payload = provider.request(key, prompt, user_input, model, max_tokens)

    last = ""
    started = time.monotonic()

    for attempt in range(max_attempts):
        wait = None
        if limiter is not None:
            await limiter.wait()
        try:
            response = await client.post(provider.url, json=payload, headers=headers)
        except httpx.RequestError as err:
            # Сеть отвалилась до ответа: пробуем ещё раз
            last = f"сеть: {err}"
        else:
            if response.status_code == 200:
                try:
                    parsed = provider.parse(response.json(), model)
                except (ValueError, ProviderError) as err:
                    raise ModelError(f"{provider.name}: непонятный ответ: {err}") from None
                if parsed.truncated_empty:
                    # Токены потрачены, а ответа нет. Повтор даст то же самое,
                    # поэтому сразу сбой с понятной причиной, а не «не прошло»
                    raise ModelError(
                        f"ответ оборван на потолке {max_tokens} токенов раньше, чем начался текст "
                        "(модель всё потратила на рассуждение)"
                    )
                return Answer(
                    text=parsed.text,
                    model=parsed.model,
                    input_tokens=parsed.usage.input_tokens,
                    output_tokens=parsed.usage.output_tokens,
                    attempts=attempt + 1,
                    seconds=round(time.monotonic() - started, 3),
                    cache_read_tokens=parsed.usage.cache_read_tokens,
                )

            if response.status_code not in RETRY_CODES:
                raise ModelError(f"{response.status_code}: {response.text[:200]}")

            last = f"{response.status_code}: {response.text[:200]}"
            wait = retry_after(response)

        if attempt < max_attempts - 1:
            # Сервер сам сказал, сколько ждать: верим ему (с небольшим разбросом,
            # чтобы параллельные запросы не вернулись в одну и ту же секунду).
            # Не сказал: пауза с удвоением.
            if wait is not None:
                await pause(wait + random.random())
            else:
                await pause(backoff_delay(attempt))

    raise ModelError(f"Не удалось за {max_attempts} попыток. Последнее: {last}")


async def ask_many(
    jobs: list[tuple[str, str, str]],
    limit: int = 5,
    timeout: float = 60.0,
    provider=None,
    rpm: float | None = None,
) -> list:
    """Много вопросов сразу, но не больше limit одновременно.

    jobs — список из (промпт, входной текст, модель).
    rpm — не больше стольких запросов в минуту (None — без ограничения).
    Ошибка одного запроса не роняет прогон: она возвращается в списке
    на своём месте, чтобы в отчёте было видно, что именно не ответило.
    """
    gate = asyncio.Semaphore(limit)
    limiter = RateLimiter(rpm) if rpm else None

    async with httpx.AsyncClient(timeout=timeout) as client:

        async def one(prompt, user_input, model):
            async with gate:
                return await ask(client, prompt, user_input, model, provider=provider, limiter=limiter)

        return await asyncio.gather(
            *(one(*job) for job in jobs), return_exceptions=True
        )
