import httpx
import pytest

from core.client import Answer, ModelError, ask, backoff_delay

MODEL = "claude-sonnet-4-6"


def ok_body(text="water=0.3"):
    return {
        "model": MODEL,
        "content": [{"type": "text", "text": text}],
        "usage": {"input_tokens": 12, "output_tokens": 4},
    }


def client_from(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestBackoff:
    def test_растёт_с_каждой_попыткой(self):
        assert backoff_delay(0) < backoff_delay(3)

    def test_не_превышает_потолок(self):
        assert backoff_delay(20, cap=30) <= 30

    def test_разброс_даёт_разные_значения(self):
        values = {backoff_delay(2) for _ in range(20)}
        assert len(values) > 1


class TestAsk:
    @pytest.mark.asyncio
    async def test_успешный_ответ(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

        async with client_from(lambda r: httpx.Response(200, json=ok_body())) as c:
            answer = await ask(c, "промпт", "выпил 300 мл", MODEL)

        assert isinstance(answer, Answer)
        assert answer.text == "water=0.3"
        assert answer.input_tokens == 12
        assert answer.attempts == 1

    @pytest.mark.asyncio
    async def test_без_ключа_сразу_ошибка(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        async with client_from(lambda r: httpx.Response(200, json=ok_body())) as c:
            with pytest.raises(ModelError, match="ANTHROPIC_API_KEY"):
                await ask(c, "промпт", "текст", MODEL)

    @pytest.mark.asyncio
    async def test_ошибка_запроса_не_повторяется(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(400, text="bad request")

        async with client_from(handler) as c:
            with pytest.raises(ModelError, match="400"):
                await ask(c, "промпт", "текст", MODEL)

        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_отказ_повторяется_и_вторая_попытка_проходит(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        monkeypatch.setattr("core.client.backoff_delay", lambda *a, **k: 0)
        calls = []

        def handler(request):
            calls.append(1)
            if len(calls) == 1:
                return httpx.Response(429, text="slow down")
            return httpx.Response(200, json=ok_body())

        async with client_from(handler) as c:
            answer = await ask(c, "промпт", "текст", MODEL)

        assert answer.attempts == 2
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_попытки_закончились(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        monkeypatch.setattr("core.client.backoff_delay", lambda *a, **k: 0)
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(503, text="unavailable")

        async with client_from(handler) as c:
            with pytest.raises(ModelError, match="3 попыток"):
                await ask(c, "промпт", "текст", MODEL, max_attempts=3)

        assert len(calls) == 3
