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


def test_полный_прогон_с_подменённой_моделью(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "load_env", lambda: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

    async def ask(jobs, limit):
        # Вариант rules отвечает верно на задачу про зал, short нет
        return [
            Answer("gym=нет" if "пропустил" in prompt else "gym=да", model, 5, 1, 1, 0.1)
            for prompt, user_input, model in jobs
        ]

    async def fake_run(variants, cases, model, limit):
        from core.runner import run
        return await run(variants, cases, model, limit=limit, ask=ask)

    monkeypatch.setattr(cli, "run", fake_run)
    out_file = tmp_path / "run.json"

    assert cli.main(ARGS + ["--out", str(out_file), "--model", "m"]) == 0
    out = capsys.readouterr().out
    assert out_file.exists()
    assert "Расхождения" in out
    assert "gym_no: short нет, rules да" in out
