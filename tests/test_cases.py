import pytest

from core.cases import CaseError, load_cases


def write(tmp_path, text):
    path = tmp_path / "cases.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_загружает_рабочий_набор():
    cases = load_cases("cases/parse_day.yaml")
    assert len(cases) == 7
    assert cases[0].id == "water_ml"
    assert "300" in cases[0].input


def test_expect_необязателен(tmp_path):
    path = write(tmp_path, "- id: a\n  input: привет\n")
    cases = load_cases(path)
    assert cases[0].expect == {}


def test_нет_id(tmp_path):
    path = write(tmp_path, "- input: привет\n")
    with pytest.raises(CaseError, match="id"):
        load_cases(path)


def test_повтор_id(tmp_path):
    path = write(tmp_path, "- id: a\n  input: раз\n- id: a\n  input: два\n")
    with pytest.raises(CaseError, match="уже есть"):
        load_cases(path)


def test_нет_input(tmp_path):
    path = write(tmp_path, "- id: a\n")
    with pytest.raises(CaseError, match="input"):
        load_cases(path)


def test_опечатка_в_названии_проверки(tmp_path):
    path = write(tmp_path, "- id: a\n  input: привет\n  expect:\n    contain_all: [да]\n")
    with pytest.raises(CaseError, match="неизвестная проверка"):
        load_cases(path)


def test_пустой_файл(tmp_path):
    path = write(tmp_path, "[]\n")
    with pytest.raises(CaseError, match="ни одной"):
        load_cases(path)
