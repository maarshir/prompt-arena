import json

import httpx
import pytest

from core.cases import Case
from core.client import Answer, ModelError
from core.runner import Result, disagreements, run, save, summarize
from core.variants import Variant

VARIANTS = [Variant("a", "промпт А"), Variant("b", "промпт Б")]
CASES = [
    Case("water", "выпил 300 мл", {"contains_all": ["water=0.3"]}),
    Case("gym", "пропустил зал", {"contains_all": ["gym=нет"]}),
]


def fake_ask(replies):
    """Подмена ask_many: ответ берётся из словаря по (промпт, вход)."""
    seen = []

    async def ask(jobs, limit):
        seen.append((jobs, limit))
        out = []
        for prompt, user_input, model in jobs:
            reply = replies[(prompt, user_input)]
            if isinstance(reply, BaseException):
                out.append(reply)
            else:
                out.append(Answer(reply, model, 10, 3, 1, 0.5))
        return out

    ask.seen = seen
    return ask


async def test_все_пары_и_проверки():
    ask = fake_ask({
        ("промпт А", "выпил 300 мл"): "water=0.3",
        ("промпт А", "пропустил зал"): "gym=да",
        ("промпт Б", "выпил 300 мл"): "water=0.3",
        ("промпт Б", "пропустил зал"): "gym=нет",
    })
    results = await run(VARIANTS, CASES, "m", limit=3, ask=ask)

    assert [(r.variant, r.case, r.passed) for r in results] == [
        ("a", "water", True),
        ("a", "gym", False),
        ("b", "water", True),
        ("b", "gym", True),
    ]
    jobs, limit = ask.seen[0]
    assert limit == 3
    assert jobs[0] == ("промпт А", "выпил 300 мл", "m")
    assert results[0].input_tokens == 10 and results[0].seconds == 0.5


async def test_сбой_не_роняет_прогон_и_записан_отдельно():
    ask = fake_ask({
        ("промпт А", "выпил 300 мл"): ModelError("429 и попытки кончились"),
        ("промпт А", "пропустил зал"): "gym=нет",
        ("промпт Б", "выпил 300 мл"): "water=0.3",
        ("промпт Б", "пропустил зал"): "gym=нет",
    })
    results = await run(VARIANTS, CASES, "m", ask=ask)

    broken = results[0]
    assert broken.passed is False
    assert broken.answer is None
    assert "429" in broken.error
    assert results[1].error is None


def r(variant, case, passed, error=None, tokens=(0, 0)):
    return Result(variant, case, passed, error=error, input_tokens=tokens[0], output_tokens=tokens[1])


def test_итоги_по_вариантам():
    results = [
        r("a", "x", True, tokens=(10, 2)),
        r("a", "y", False, tokens=(10, 3)),
        r("a", "z", False, error="сеть"),
        r("b", "x", True),
    ]
    a, b = summarize(results)
    assert (a.variant, a.passed, a.failed, a.errors) == ("a", 1, 1, 1)
    assert (a.input_tokens, a.output_tokens) == (20, 5)
    assert (b.variant, b.passed, b.failed, b.errors) == ("b", 1, 0, 0)


def test_расхождения_только_там_где_варианты_разошлись():
    results = [
        r("a", "same", True), r("b", "same", True),
        r("a", "diff", True), r("b", "diff", False),
        r("a", "both_bad", False), r("b", "both_bad", False),
        r("a", "broken", True), r("b", "broken", False, error="сеть"),
    ]
    assert disagreements(results) == {"diff": {"a": True, "b": False}}


def test_сохранение(tmp_path):
    path = save([r("a", "x", True)], tmp_path / "sub" / "run.json", {"model": "m"})
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["meta"]["model"] == "m"
    assert "saved_at" in data["meta"]
    assert data["results"][0]["variant"] == "a"
    assert data["summary"][0]["passed"] == 1


async def test_целиком_через_настоящий_клиент(monkeypatch):
    """Прогон через настоящий ask_many, подменена только сеть.

    Первый запрос получает 429 и проходит со второй попытки.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr("core.client.backoff_delay", lambda *a, **k: 0)
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 1:
            return httpx.Response(429, text="slow down")
        text = "water=0.3" if "300" in body["messages"][0]["content"] else "gym=нет"
        return httpx.Response(200, json={
            "model": body["model"],
            "content": [{"type": "text", "text": text}],
            "usage": {"input_tokens": 7, "output_tokens": 2},
        })

    real = httpx.AsyncClient

    def mocked(**kwargs):
        return real(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr("core.client.httpx.AsyncClient", mocked)

    results = await run(VARIANTS, CASES, "m", limit=1)

    assert all(x.passed for x in results)
    assert len(calls) == 5
    assert sorted(x.attempts for x in results) == [1, 1, 1, 2]
    assert calls[-1]["system"] in {"промпт А", "промпт Б"}
