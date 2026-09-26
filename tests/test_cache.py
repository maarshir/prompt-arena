import json

from core.cache import AnswerCache, cache_key, with_cache
from core.cases import Case
from core.client import Answer, ModelError
from core.runner import run, summarize
from core.variants import Variant


def counting_ask(reply=lambda prompt, user_input: "ok", fail=()):
    """Подмена ask_many, которая считает, сколько запросов ушло в модель."""
    sent = []

    async def ask(jobs, limit=5):
        sent.extend(jobs)
        out = []
        for prompt, user_input, model in jobs:
            if (prompt, user_input) in fail:
                out.append(ModelError("503"))
            else:
                out.append(Answer(reply(prompt, user_input), model, 10, 3, 2, 1.5))
        return out

    ask.sent = sent
    return ask


def test_ключ_зависит_от_всего_что_влияет_на_ответ():
    base = cache_key("промпт", "вход", "m")
    assert base == cache_key("промпт", "вход", "m")
    assert base != cache_key("промпт!", "вход", "m")
    assert base != cache_key("промпт", "вход!", "m")
    assert base != cache_key("промпт", "вход", "m2")
    assert base != cache_key("промпт", "вход", "m", max_tokens=100)


def test_ключ_не_путает_границу_между_полями():
    # При склейке строк через разделитель эти два запроса совпали бы
    assert cache_key("a|b", "c", "m") != cache_key("a", "b|c", "m")


def test_сохранить_и_прочитать(tmp_path):
    cache = AnswerCache(tmp_path)
    key = cache_key("п", "в", "m")
    assert cache.get(key) is None

    cache.put(key, Answer("ответ", "m-2026", 10, 3, 2, 1.5))
    got = cache.get(key)

    assert got == Answer("ответ", "m-2026", 10, 3, 2, 1.5, cached=True)
    # Один файл на ответ, в подпапке по первым знакам ключа, без временных файлов
    files = list(tmp_path.rglob("*"))
    assert [f.name for f in files if f.is_file()] == [f"{key}.json"]


def test_битый_файл_это_промах_а_не_падение(tmp_path):
    cache = AnswerCache(tmp_path)
    key = cache_key("п", "в", "m")
    cache.put(key, Answer("ответ", "m", 1, 1, 1))
    path = next(tmp_path.rglob("*.json"))

    path.write_text("{не json", encoding="utf-8")
    assert cache.get(key) is None

    path.write_text(json.dumps({"answer": {"лишнее": 1}}), encoding="utf-8")
    assert cache.get(key) is None


async def test_второй_раз_в_модель_не_ходит(tmp_path):
    model = counting_ask()
    ask = with_cache(model, AnswerCache(tmp_path))
    jobs = [("п1", "в", "m"), ("п2", "в", "m")]

    first = await ask(jobs, limit=2)
    second = await ask(jobs, limit=2)

    assert len(model.sent) == 2
    assert [a.cached for a in first] == [False, False]
    assert [a.cached for a in second] == [True, True]
    assert [a.text for a in second] == ["ok", "ok"]


async def test_в_модель_уходят_только_промахи_и_без_повторов(tmp_path):
    model = counting_ask()
    ask = with_cache(model, AnswerCache(tmp_path))
    await ask([("п1", "в", "m")])
    model.sent.clear()

    # п1 уже в кэше, п2 встречается дважды: в модель должен уйти один запрос
    out = await ask([("п1", "в", "m"), ("п2", "в", "m"), ("п2", "в", "m")])

    assert model.sent == [("п2", "в", "m")]
    assert [a.cached for a in out] == [True, False, False]


async def test_ошибка_не_запоминается(tmp_path):
    cache = AnswerCache(tmp_path)
    failing = counting_ask(fail={("п", "в")})
    out = await with_cache(failing, cache)([("п", "в", "m")])
    assert isinstance(out[0], ModelError)
    assert cache.get(cache_key("п", "в", "m")) is None

    healthy = counting_ask()
    out = await with_cache(healthy, cache)([("п", "в", "m")])
    assert out[0].text == "ok" and not out[0].cached
    assert len(healthy.sent) == 1


async def test_прогон_с_кэшем_помечает_ответы_и_считает_в_итогах(tmp_path):
    variants = [Variant("a", "промпт А"), Variant("b", "промпт Б")]
    cases = [Case("water", "выпил 300 мл", {"contains_all": ["water=0.3"]})]
    model = counting_ask(reply=lambda p, i: "water=0.3")
    ask = with_cache(model, AnswerCache(tmp_path))

    await run(variants, cases, "m", ask=ask)
    variants.append(Variant("c", "промпт В"))
    results = await run(variants, cases, "m", ask=ask)

    # Добавили вариант: спросили только его
    assert len(model.sent) == 3
    assert [(r.variant, r.cached, r.passed) for r in results] == [
        ("a", True, True),
        ("b", True, True),
        ("c", False, True),
    ]
    # Токены у ответа из кэша остаются: это цена ответа, а не трата этого запуска
    assert results[0].input_tokens == 10
    assert [s.cached for s in summarize(results)] == [1, 1, 0]
