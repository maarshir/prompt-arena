"""Поставщики моделей: Anthropic и Groq.

У каждого свой адрес, свой ключ, свой формат запроса и ответа. Всё, чем
они отличаются, собрано здесь, а повторы, паузы и кэш общие (core.client,
core.cache). Groq отвечает в формате OpenAI Chat Completions, поэтому
класс OpenAICompatible подойдёт и для других совместимых API.
"""

from dataclasses import dataclass, field

from token_counter import Usage


class ProviderError(ValueError):
    """Неизвестный поставщик или ответ не того формата."""


@dataclass(frozen=True)
class Parsed:
    """Разобранный ответ поставщика."""
    text: str
    model: str
    usage: Usage
    # Ответ оборван потолком длины и текста нет: модель всё потратила на рассуждение
    truncated_empty: bool = False


@dataclass(frozen=True)
class Anthropic:
    name: str = "anthropic"
    key_env: str = "ANTHROPIC_API_KEY"
    url: str = "https://api.anthropic.com/v1/messages"
    version: str = "2023-06-01"
    default_model: str = "claude-sonnet-4-6"
    max_tokens: int = 512
    max_attempts: int = 4
    # Платный API без жёсткого бесплатного лимита: частоту не ограничиваем
    rpm: float | None = None

    def extra(self, model: str) -> dict:
        return {}

    def request(self, key: str, prompt: str, user_input: str, model: str, max_tokens: int):
        headers = {
            "x-api-key": key,
            "anthropic-version": self.version,
            "content-type": "application/json",
        }
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "system": prompt,
            "messages": [{"role": "user", "content": user_input}],
        }
        return headers, payload

    def parse(self, data: dict, model: str) -> Parsed:
        text = "".join(
            block.get("text", "")
            for block in data.get("content", [])
            if block.get("type") == "text"
        )
        return Parsed(text.strip(), data.get("model", model), Usage.from_api(data.get("usage") or {}))


@dataclass(frozen=True)
class OpenAICompatible:
    name: str
    key_env: str
    url: str
    default_model: str
    version: str = "openai-chat-v1"
    # Больше, чем у Anthropic: у моделей с рассуждением (gpt-oss) рассуждение
    # входит в тот же потолок, и при 512 ответ может не успеть начаться
    max_tokens: int = 1024
    # Бесплатный уровень часто отвечает 429, повторов нужно больше
    max_attempts: int = 8
    rpm: float | None = None
    # Дополнительные поля запроса для моделей, имя которых начинается с ключа
    extras: dict = field(default_factory=dict)

    def extra(self, model: str) -> dict:
        for prefix, fields in self.extras.items():
            if model.startswith(prefix):
                return dict(fields)
        return {}

    def request(self, key: str, prompt: str, user_input: str, model: str, max_tokens: int):
        headers = {"authorization": f"Bearer {key}", "content-type": "application/json"}
        payload = {
            "model": model,
            "max_completion_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_input},
            ],
            **self.extra(model),
        }
        return headers, payload

    def parse(self, data: dict, model: str) -> Parsed:
        choices = data.get("choices") or []
        if not choices:
            raise ProviderError("в ответе нет choices")
        choice = choices[0]
        text = ((choice.get("message") or {}).get("content") or "").strip()
        return Parsed(
            text=text,
            model=data.get("model", model),
            usage=Usage.from_openai(data.get("usage") or {}),
            truncated_empty=not text and choice.get("finish_reason") == "length",
        )


ANTHROPIC = Anthropic()

GROQ = OpenAICompatible(
    name="groq",
    key_env="GROQ_API_KEY",
    url="https://api.groq.com/openai/v1/chat/completions",
    default_model="openai/gpt-oss-120b",
    # На странице лимитов Groq (сверено 27.09.2026) у бесплатного уровня для gpt-oss
    # 30 запросов в минуту. Берём меньше, с запасом; меняется через --rpm.
    rpm=20,
    extras={
        # gpt-oss рассуждает перед ответом. Для разбора коротких фраз хватает
        # низкого усилия, а токены рассуждения идут в лимит токенов в минуту.
        # Сам текст рассуждения не нужен, не гоняем его по сети.
        "openai/gpt-oss": {"reasoning_effort": "low", "include_reasoning": False},
    },
)

PROVIDERS = {p.name: p for p in (ANTHROPIC, GROQ)}


def get(name: str):
    try:
        return PROVIDERS[name]
    except KeyError:
        raise ProviderError(f"Неизвестный поставщик {name!r}, есть: {', '.join(PROVIDERS)}") from None


def for_model(model: str, name: str | None = None):
    """Поставщик по флагу или по имени модели.

    Правило по имени простое: у моделей на Groq в имени есть косая черта
    (openai/gpt-oss-120b, meta-llama/...), у Claude нет. Для имён без черты
    на Groq (например llama-3.3-70b-versatile) нужен явный --provider groq.
    """
    if name:
        return get(name)
    return GROQ if "/" in model else ANTHROPIC
