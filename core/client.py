"""Вызов модели. Асинхронный, с повторами и потолком на одновременные запросы."""

import asyncio
import os
import random
from dataclasses import dataclass

import httpx

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"

# Коды, после которых есть смысл повторить: слишком часто, перегрузка, сбой сервера.
# 400 или 401 повторять бессмысленно: запрос не станет верным от повтора.
RETRY_CODES = {429, 500, 502, 503, 529}


class ModelError(RuntimeError):
    """Модель не ответила и повторять бесполезно."""


@dataclass
class Answer:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    attempts: int


def backoff_delay(attempt: int, base: float = 1.0, cap: float = 30.0) -> float:
    """Пауза перед следующей попыткой: удваивается, но с разбросом.

    Разброс нужен, чтобы десяток параллельных запросов, получив отказ
    одновременно, не пошёл повторять тоже одновременно и снова не положил
    сервер. Без него повторы сбиваются в волны.
    """
    return min(cap, base * 2 ** attempt) * (0.5 + random.random() / 2)


async def ask(
    client: httpx.AsyncClient,
    prompt: str,
    user_input: str,
    model: str,
    max_attempts: int = 4,
    max_tokens: int = 512,
) -> Answer:
    """Один вопрос к модели. Повторяет только то, что имеет шанс пройти."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ModelError("Не задана переменная окружения ANTHROPIC_API_KEY")

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "system": prompt,
        "messages": [{"role": "user", "content": user_input}],
    }
    headers = {
        "x-api-key": key,
        "anthropic-version": API_VERSION,
        "content-type": "application/json",
    }

    last = ""

    for attempt in range(max_attempts):
        try:
            response = await client.post(API_URL, json=payload, headers=headers)
        except httpx.RequestError as err:
            # Сеть отвалилась до ответа: пробуем ещё раз
            last = f"сеть: {err}"
        else:
            if response.status_code == 200:
                data = response.json()
                text = "".join(
                    block.get("text", "")
                    for block in data.get("content", [])
                    if block.get("type") == "text"
                )
                usage = data.get("usage", {})
                return Answer(
                    text=text.strip(),
                    model=data.get("model", model),
                    input_tokens=usage.get("input_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0),
                    attempts=attempt + 1,
                )

            if response.status_code not in RETRY_CODES:
                raise ModelError(f"{response.status_code}: {response.text[:200]}")

            last = f"{response.status_code}: {response.text[:200]}"

        if attempt < max_attempts - 1:
            await asyncio.sleep(backoff_delay(attempt))

    raise ModelError(f"Не удалось за {max_attempts} попыток. Последнее: {last}")


async def ask_many(
    jobs: list[tuple[str, str, str]],
    limit: int = 5,
    timeout: float = 60.0,
) -> list:
    """Много вопросов сразу, но не больше limit одновременно.

    jobs — список из (промпт, входной текст, модель).
    Ошибка одного запроса не роняет прогон: она возвращается в списке
    на своём месте, чтобы в отчёте было видно, что именно не ответило.
    """
    gate = asyncio.Semaphore(limit)

    async with httpx.AsyncClient(timeout=timeout) as client:

        async def one(prompt, user_input, model):
            async with gate:
                return await ask(client, prompt, user_input, model)

        return await asyncio.gather(
            *(one(*job) for job in jobs), return_exceptions=True
        )
