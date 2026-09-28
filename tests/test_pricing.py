import json
from decimal import Decimal

import run as cli
from core.pricing import estimate_upper, price_run
from core.runner import Result
from tests.test_run_cli import ARGS, fake_model

# Своя таблица цен, чтобы тесты не зависели от того, как поменяются настоящие цены
PRICES = {
    "models": {
        "test-model": {
            "provider": "test", "input": "3", "output": "15",
            "cache_write": None, "cache_read": None,
            "checked": "2026-09-27", "source": "https://example.com",
        }
    }
}


def prices_file(tmp_path):
    path = tmp_path / "prices.json"
    path.write_text(json.dumps(PRICES), encoding="utf-8")
    return path


def r(variant, case, tokens=(0, 0), cached=False, error=None):
    return Result(variant, case, passed=error is None, error=error,
                  input_tokens=tokens[0], output_tokens=tokens[1], cached=cached)


def test_цена_по_вариантам_и_отдельно_потраченное(tmp_path):
    results = [
        r("a", "x", (1000, 100)),               # 0.003 + 0.0015
        r("a", "y", (1000, 100), cached=True),  # столько же, но из кэша
        r("b", "x", (2000, 0)),                 # 0.006
        r("b", "y", error="сеть"),              # сбой: токенов нет, денег нет
    ]
    rc = price_run(results, "test-model", prices_file(tmp_path))

    assert rc.known and rc.checked == "2026-09-27"
    a, b = rc.variants
    assert (a.variant, a.answers, a.spent) == ("a", Decimal("0.009"), Decimal("0.0045"))
    assert (b.variant, b.answers, b.spent) == ("b", Decimal("0.006"), Decimal("0.006"))
    assert rc.answers == Decimal("0.015")
    assert rc.spent == Decimal("0.0105")


def test_дата_в_имени_модели_не_мешает(tmp_path):
    rc = price_run([r("a", "x", (10, 10))], "test-model-20260101", prices_file(tmp_path))
    assert rc.known


def test_неизвестная_модель_не_роняет_прогон(tmp_path):
    rc = price_run([r("a", "x", (10, 10))], "другая", prices_file(tmp_path))
    assert not rc.known
    assert "другая" in rc.reason
    assert rc.to_json() == {"model": "другая", "known": False, "reason": rc.reason}


def test_битая_таблица_цен_не_роняет_прогон(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{не json", encoding="utf-8")
    rc = price_run([r("a", "x", (10, 10))], "test-model", bad)
    assert not rc.known and "JSON" in rc.reason


def test_деньги_в_json_строками(tmp_path):
    rc = price_run([r("a", "x", (1, 1))], "test-model", prices_file(tmp_path))
    data = rc.to_json()
    assert data["answers_usd"] == "0.000018"
    assert data["variants"] == [{"variant": "a", "answers_usd": "0.000018", "spent_usd": "0.000018"}]
    json.dumps(data)  # сериализуется без default=str


def test_прикидка_сверху_считает_ответ_полным(tmp_path):
    upper, reason = estimate_upper([("", "")], "test-model", prices_file(tmp_path), max_tokens=1000)
    assert reason is None
    assert upper == Decimal("0.015")  # пустой вход, ответ 1000 токенов по 15 за миллион

    more, _ = estimate_upper([("промпт", "вход")] * 2, "test-model", prices_file(tmp_path), max_tokens=1000)
    assert more > 2 * upper


def test_прикидка_без_цены(tmp_path):
    upper, reason = estimate_upper([("a", "b")], "нет-такой", prices_file(tmp_path))
    assert upper is None and "нет-такой" in reason


# Через командную строку

def base(tmp_path, model="test-model"):
    return ARGS + ["--model", model, "--cache-dir", str(tmp_path / "c"), "--prices", str(prices_file(tmp_path))]


def test_прогон_показывает_и_сохраняет_цену(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "load_env", lambda: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(cli, "ask_many", fake_model([]))
    out_file = tmp_path / "run.json"

    assert cli.main(base(tmp_path) + ["--out", str(out_file)]) == 0
    out = capsys.readouterr().out
    # fake_model: 5 токенов входа и 1 выхода на ответ, 7 задач на вариант
    # (5 * 3 + 1 * 15) / 1e6 = 0.00003 за ответ, 0.00021 за вариант
    assert "$0.00021" in out
    assert "Цена ответов: $0.00042, потрачено в этом запуске: $0.00042" in out

    cost = json.loads(out_file.read_text(encoding="utf-8"))["cost"]
    assert Decimal(cost["spent_usd"]) == Decimal("0.00042")
    assert [Decimal(v["answers_usd"]) for v in cost["variants"]] == [Decimal("0.00021")] * 2


def test_повтор_из_кэша_ничего_не_стоит(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "load_env", lambda: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(cli, "ask_many", fake_model([]))

    assert cli.main(base(tmp_path) + ["--out", str(tmp_path / "1.json")]) == 0
    capsys.readouterr()
    assert cli.main(base(tmp_path) + ["--out", str(tmp_path / "2.json")]) == 0
    assert "Цена ответов: $0.00042, потрачено в этом запуске: $0.00" in capsys.readouterr().out


def test_модель_без_цены_прогон_всё_равно_проходит(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "load_env", lambda: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(cli, "ask_many", fake_model([]))
    out_file = tmp_path / "run.json"

    assert cli.main(base(tmp_path, model="m") + ["--out", str(out_file)]) == 0
    out = capsys.readouterr().out
    assert "Цена неизвестна: Нет цены для модели m" in out
    assert "urgent_negated: short нет, rules да" in out
    assert json.loads(out_file.read_text(encoding="utf-8"))["cost"]["known"] is False


def test_dry_run_с_прикидкой(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "load_env", lambda: None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert cli.main(base(tmp_path) + ["--dry-run"]) == 0
    assert "Прикидка сверху для 14 запросов: ≈$" in capsys.readouterr().out


def test_dry_run_не_считает_то_что_уже_в_кэше(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "load_env", lambda: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(cli, "ask_many", fake_model([]))
    assert cli.main(base(tmp_path) + ["--out", str(tmp_path / "1.json")]) == 0
    capsys.readouterr()

    assert cli.main(base(tmp_path) + ["--dry-run"]) == 0
    assert "Прикидка сверху для 0 запросов: ≈$0.00" in capsys.readouterr().out
