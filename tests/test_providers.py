"""Поставщик Groq, выбор поставщика, retry-after и ограничение частоты. Сеть подменена."""

import json
from decimal import Decimal

import httpx
import pytest

import run as cli
from core.cache import cache_key
from core.client import ModelError, RateLimiter, ask, ask_many, retry_after
from core.pricing import price_run
from core.providers import ANTHROPIC, GROQ, ProviderError, for_model
from core.runner import Result
from tests.test_run_cli import ARGS, fake_model

GPT = "openai/gpt-oss-120b"


def groq_body(text="water=0.3", cached=0, finish="stop"):
    """Ответ в формате OpenAI Chat Completions, как его отдаёт Groq."""
    usage = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
    if cached:
        usage["prompt_tokens_details"] = {"cached_tokens": cached}
    return {
        "model": GPT,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                     "finish_reason": finish}],
        "usage": usage,
    }


def client_from(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture
def no_sleep(monkeypatch):
    """Паузы не ждём, а запоминаем, сколько просили."""
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr("core.client.pause", fake_sleep)
    return slept


class TestВыборПоставщика:
    def test_по_имени_модели(self):
        assert for_model("claude-sonnet-4-6") is ANTHROPIC
        assert for_model(GPT) is GROQ
        assert for_model("meta-llama/llama-4-scout-17b-16e-instruct") is GROQ

    def test_явный_поставщик_важнее_имени(self):
        assert for_model("llama-3.3-70b-versatile", "groq") is GROQ
        assert for_model(GPT, "anthropic") is ANTHROPIC

    def test_неизвестный_поставщик(self):
        with pytest.raises(ProviderError, match="groq"):
            for_model("x", "openrouter")


class TestЗапросGroq:
    async def test_адрес_ключ_и_тело_запроса(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
        seen = []

        def handler(request):
            seen.append(request)
            return httpx.Response(200, json=groq_body())

        async with client_from(handler) as c:
            answer = await ask(c, "промпт", "выпил 300 мл", GPT)

        request = seen[0]
        body = json.loads(request.content)
        assert str(request.url) == "https://api.groq.com/openai/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer gsk_test"
        assert body["messages"] == [
            {"role": "system", "content": "промпт"},
            {"role": "user", "content": "выпил 300 мл"},
        ]
        assert body["max_completion_tokens"] == GROQ.max_tokens
        # у gpt-oss низкое усилие рассуждения и без текста рассуждения в ответе
        assert body["reasoning_effort"] == "low"
        assert body["include_reasoning"] is False
        assert (answer.text, answer.input_tokens, answer.output_tokens) == ("water=0.3", 100, 20)

    async def test_у_других_моделей_нет_полей_рассуждения(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "k")
        seen = []

        def handler(request):
            seen.append(json.loads(request.content))
            return httpx.Response(200, json=groq_body())

        async with client_from(handler) as c:
            await ask(c, "п", "в", "llama-3.3-70b-versatile", provider=GROQ)

        assert "reasoning_effort" not in seen[0]

    async def test_кэш_промпта_groq_отдельно_от_входа(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "k")
        async with client_from(lambda r: httpx.Response(200, json=groq_body(cached=64))) as c:
            answer = await ask(c, "п", "в", GPT)
        # prompt_tokens 100 уже включают 64 из кэша: платим 36 по цене входа и 64 по цене кэша
        assert (answer.input_tokens, answer.cache_read_tokens) == (36, 64)

    async def test_без_ключа_groq_понятная_ошибка(self, monkeypatch):
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "есть, но не тот")
        async with client_from(lambda r: httpx.Response(200, json=groq_body())) as c:
            with pytest.raises(ModelError, match="GROQ_API_KEY"):
                await ask(c, "п", "в", GPT)

    async def test_обрезанный_пустой_ответ_это_сбой_без_повторов(self, monkeypatch, no_sleep):
        monkeypatch.setenv("GROQ_API_KEY", "k")
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(200, json=groq_body(text="", finish="length"))

        async with client_from(handler) as c:
            with pytest.raises(ModelError, match="рассуждение"):
                await ask(c, "п", "в", GPT)
        assert len(calls) == 1

    async def test_ответ_без_choices_это_сбой(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "k")
        async with client_from(lambda r: httpx.Response(200, json={"usage": {}})) as c:
            with pytest.raises(ModelError, match="choices"):
                await ask(c, "п", "в", GPT)


class TestRetryAfter:
    def resp(self, value):
        return httpx.Response(429, headers={} if value is None else {"retry-after": value})

    def test_секунды(self):
        assert retry_after(self.resp("7")) == 7
        assert retry_after(self.resp("2.5")) == 2.5

    def test_нет_или_мусор(self):
        assert retry_after(self.resp(None)) is None
        assert retry_after(self.resp("soon")) is None

    def test_потолок_и_отрицательное(self):
        assert retry_after(self.resp("100000")) == 90
        assert retry_after(self.resp("-3")) == 0

    def test_дата_в_прошлом(self):
        assert retry_after(self.resp("Wed, 21 Oct 2015 07:28:00 GMT")) == 0

    async def test_429_ждём_сколько_сказал_сервер(self, monkeypatch, no_sleep):
        monkeypatch.setenv("GROQ_API_KEY", "k")
        calls = []

        def handler(request):
            calls.append(1)
            if len(calls) == 1:
                return httpx.Response(429, headers={"retry-after": "12"}, text="rate limit")
            return httpx.Response(200, json=groq_body())

        async with client_from(handler) as c:
            answer = await ask(c, "п", "в", GPT)

        assert answer.attempts == 2
        # 12 секунд от сервера и разброс до секунды сверху, а не пауза с удвоением
        assert len(no_sleep) == 1 and 12 <= no_sleep[0] < 13

    async def test_у_groq_больше_попыток(self, monkeypatch, no_sleep):
        monkeypatch.setenv("GROQ_API_KEY", "k")
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(429, text="rate limit")

        async with client_from(handler) as c:
            with pytest.raises(ModelError, match=f"{GROQ.max_attempts} попыток"):
                await ask(c, "п", "в", GPT)
        assert len(calls) == GROQ.max_attempts > ANTHROPIC.max_attempts


class TestОграничениеЧастоты:
    async def test_запросы_идут_с_равным_шагом(self):
        now = [100.0]
        slept = []

        async def sleep(seconds):
            slept.append(seconds)

        limiter = RateLimiter(30, clock=lambda: now[0], sleep=sleep)
        for _ in range(3):
            await limiter.wait()
        # первый сразу, дальше каждые 2 секунды от первого
        assert slept == [2.0, 4.0]

        # если запросов долго не было, пауза не копится
        now[0] = 1000.0
        await limiter.wait()
        assert slept == [2.0, 4.0]

    def test_ноль_запрещён(self):
        with pytest.raises(ValueError):
            RateLimiter(0)

    async def test_ask_many_соблюдает_частоту(self, monkeypatch, no_sleep):
        monkeypatch.setenv("GROQ_API_KEY", "k")
        real = httpx.AsyncClient
        monkeypatch.setattr(
            "core.client.httpx.AsyncClient",
            lambda **kw: real(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=groq_body())), **kw),
        )
        # ограничитель по умолчанию ждёт через core.client.pause, она подменена
        out = await ask_many([("п", str(i), GPT) for i in range(4)], limit=4, provider=GROQ, rpm=60)

        assert all(a.text == "water=0.3" for a in out)
        # четыре запроса при 60 в минуту: три паузы, последняя около трёх секунд
        assert len(no_sleep) == 3
        assert max(no_sleep) == pytest.approx(3.0, abs=0.2)


class TestКэш:
    def test_поставщик_и_поля_запроса_в_ключе(self):
        assert cache_key("п", "в", "m") == cache_key("п", "в", "m", provider=ANTHROPIC)
        assert cache_key("п", "в", "m", provider=ANTHROPIC) != cache_key("п", "в", "m", provider=GROQ)
        # у gpt-oss в запросе есть reasoning_effort: он тоже влияет на ответ
        assert GROQ.extra(GPT) and not GROQ.extra("llama-3.3-70b-versatile")


class TestЦена:
    def test_кэш_промпта_groq_по_своей_цене(self):
        results = [Result("a", "x", True, input_tokens=36, output_tokens=20, cache_read_tokens=64)]
        rc = price_run(results, GPT)
        # (36 * 0.15 + 64 * 0.075 + 20 * 0.60) / 1e6 по встроенной таблице token-counter
        assert rc.known
        assert rc.answers == Decimal("0.0000222")

    def test_токены_кэша_без_цены_кэша_не_роняют_прогон(self, tmp_path):
        prices = tmp_path / "p.json"
        prices.write_text(json.dumps({"models": {"m": {
            "provider": "x", "input": "1", "output": "1", "cache_write": None, "cache_read": None,
            "checked": "2026-09-27", "source": "https://example.com"}}}), encoding="utf-8")
        rc = price_run([Result("a", "x", True, input_tokens=1, cache_read_tokens=5)], "m", prices)
        assert not rc.known and "кэш" in rc.reason


class TestКоманднаяСтрока:
    @pytest.fixture(autouse=True)
    def clean_env(self, monkeypatch):
        monkeypatch.setattr(cli, "load_env", lambda: None)
        for name in ("ANTHROPIC_API_KEY", "GROQ_API_KEY", "PROMPTDIFF_MODEL", "ARENA_MODEL",
                     "PROMPTDIFF_PROVIDER", "PROMPTDIFF_RPM"):
            monkeypatch.delenv(name, raising=False)

    def test_только_ключ_groq_значит_модель_groq(self, monkeypatch):
        assert cli.default_model() == cli.DEFAULT_MODEL
        monkeypatch.setenv("GROQ_API_KEY", "k")
        assert cli.default_model() == GROQ.default_model
        # оба ключа: как раньше, Anthropic
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        assert cli.default_model() == cli.DEFAULT_MODEL
        assert cli.default_model("groq") == GROQ.default_model
        # модель из .env важнее всего
        monkeypatch.setenv("PROMPTDIFF_MODEL", "claude-haiku-4-5")
        assert cli.default_model("groq") == "claude-haiku-4-5"

    def test_прогон_через_groq_с_ограничением_частоты(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("GROQ_API_KEY", "k")
        calls = []
        monkeypatch.setattr(cli, "ask_many", fake_model(calls))

        assert cli.main(ARGS + ["--cache-dir", str(tmp_path / "c"), "--out", str(tmp_path / "r.json")]) == 0
        out = capsys.readouterr().out
        assert f"модель: {GPT}, поставщик: groq" in out
        assert "Не больше 20 запросов в минуту" in out
        assert fake_model.options == {"provider": GROQ, "rpm": 20}
        assert json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))["meta"]["provider"] == "groq"

    def test_rpm_из_флага_и_из_env(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("GROQ_API_KEY", "k")
        monkeypatch.setattr(cli, "ask_many", fake_model([]))
        base = ARGS + ["--no-cache", "--out", str(tmp_path / "r.json")]

        monkeypatch.setenv("PROMPTDIFF_RPM", "5")
        assert cli.main(base) == 0
        assert fake_model.options["rpm"] == 5
        # флаг важнее env, 0 выключает ограничение
        assert cli.main(base + ["--rpm", "0"]) == 0
        assert fake_model.options["rpm"] is None

    def test_без_ключа_groq_понятная_ошибка(self, monkeypatch, capsys):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        assert cli.main(ARGS + ["--model", GPT]) == 2
        assert "GROQ_API_KEY" in capsys.readouterr().err

    def test_dry_run_groq_показывает_цену_и_время(self, capsys):
        assert cli.main(ARGS + ["--provider", "groq", "--dry-run", "--no-cache"]) == 0
        out = capsys.readouterr().out
        assert "поставщик: groq" in out
        assert "Прикидка сверху для 14 запросов: ≈$" in out
        # 14 запросов по 20 в минуту: 13 шагов по 3 секунды
        assert "не меньше 39 с" in out

    def test_llama_без_косой_черты_через_явный_поставщик(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("GROQ_API_KEY", "k")
        monkeypatch.setattr(cli, "ask_many", fake_model([]))
        args = ARGS + ["--provider", "groq", "--model", "llama-3.3-70b-versatile", "--no-cache",
                       "--out", str(tmp_path / "r.json")]
        assert cli.main(args) == 0
        assert fake_model.options["provider"] is GROQ
        # цены этой модели в таблице нет: прогон проходит, цена неизвестна
        assert "Цена неизвестна" in capsys.readouterr().out
