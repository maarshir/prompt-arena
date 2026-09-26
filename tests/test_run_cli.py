import os

import run as cli
from core.client import Answer


def test_load_env_не_перетирает_заданное(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# комментарий\nA_KEY='из файла'\nB_KEY=из файла\nEMPTY=\nмусор\n", encoding="utf-8")
    monkeypatch.delenv("A_KEY", raising=False)
    monkeypatch.setenv("B_KEY", "уже было")
    monkeypatch.delenv("EMPTY", raising=False)

    cli.load_env(env)

    assert os.environ["A_KEY"] == "из файла"
    assert os.environ["B_KEY"] == "уже было"
    assert "EMPTY" not in os.environ


def test_load_env_без_файла(tmp_path):
    cli.load_env(tmp_path / "нет")


ARGS = ["--prompts", "prompts/parse_day.yaml", "--cases", "cases/parse_day.yaml"]


def test_dry_run_без_ключа(monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_env", lambda: None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert cli.main(ARGS + ["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "запросов: 14" in out
    assert "--- rules ---" in out


def test_без_ключа_понятная_ошибка(monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_env", lambda: None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert cli.main(ARGS) == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


def fake_model(calls):
    """Подмена ask_many: вариант rules отвечает верно на задачу про зал, short нет."""

    async def ask(jobs, limit):
        calls.append(len(jobs))
        return [
            Answer("gym=нет" if "пропустил" in prompt else "gym=да", model, 5, 1, 1, 0.1)
            for prompt, user_input, model in jobs
        ]

    return ask


def test_полный_прогон_с_подменённой_моделью(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "load_env", lambda: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    calls = []
    monkeypatch.setattr(cli, "ask_many", fake_model(calls))
    out_file = tmp_path / "run.json"

    assert cli.main(ARGS + ["--out", str(out_file), "--model", "m", "--cache-dir", str(tmp_path / "c")]) == 0
    out = capsys.readouterr().out
    assert out_file.exists()
    assert "Расхождения" in out
    assert "gym_no: short нет, rules да" in out
    assert calls == [14]


def test_второй_прогон_из_кэша_без_ключа_и_без_запросов(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "load_env", lambda: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    calls = []
    monkeypatch.setattr(cli, "ask_many", fake_model(calls))
    cache = ["--model", "m", "--cache-dir", str(tmp_path / "c")]

    assert cli.main(ARGS + cache + ["--out", str(tmp_path / "1.json")]) == 0
    capsys.readouterr()

    # Ключ убран: все ответы в кэше, поэтому прогон всё равно проходит
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert cli.main(ARGS + cache + ["--out", str(tmp_path / "2.json")]) == 0
    out = capsys.readouterr().out
    assert calls == [14]
    assert "В кэше уже есть ответов: 14, пойдёт в модель: 0" in out
    assert "Из кэша: 14 из 14" in out
    assert "gym_no: short нет, rules да" in out


def test_no_cache_спрашивает_заново(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "load_env", lambda: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    calls = []
    monkeypatch.setattr(cli, "ask_many", fake_model(calls))
    base = ARGS + ["--model", "m", "--cache-dir", str(tmp_path / "c"), "--out", str(tmp_path / "r.json")]

    assert cli.main(base) == 0
    assert cli.main(base + ["--no-cache"]) == 0
    assert calls == [14, 14]
    assert "Из кэша" not in capsys.readouterr().out.split("запросов: 14")[-1]


def test_dry_run_показывает_сколько_в_кэше(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "load_env", lambda: None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert cli.main(ARGS + ["--dry-run", "--cache-dir", str(tmp_path / "пусто")]) == 0
    assert "В кэше уже есть ответов: 0, пойдёт в модель: 14" in capsys.readouterr().out
    assert not (tmp_path / "пусто").exists()
