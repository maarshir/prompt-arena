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


def test_exact_с_числом_без_кавычек(tmp_path):
    path = write(tmp_path, "- id: a\n  input: сколько\n  expect:\n    exact: 5\n")
    assert load_cases(path)[0].expect == {"exact": "5"}


def test_числа_в_списке_становятся_строками(tmp_path):
    path = write(tmp_path, "- id: a\n  input: x\n  expect:\n    contains_all: [300, 0.5]\n")
    assert load_cases(path)[0].expect == {"contains_all": ["300", "0.5"]}


@pytest.mark.parametrize("value", ["yes", "no", "true", "off", "null"])
def test_yes_no_без_кавычек_это_ошибка(tmp_path, value):
    path = write(tmp_path, f"- id: a\n  input: x\n  expect:\n    exact: {value}\n")
    with pytest.raises(CaseError, match="кавычки"):
        load_cases(path)


def test_yes_в_кавычках_работает(tmp_path):
    path = write(tmp_path, '- id: a\n  input: x\n  expect:\n    exact: "yes"\n')
    assert load_cases(path)[0].expect == {"exact": "yes"}


def test_строка_вместо_списка_это_ошибка(tmp_path):
    path = write(tmp_path, "- id: a\n  input: x\n  expect:\n    contains_all: gym=да\n")
    with pytest.raises(CaseError, match="нужен список"):
        load_cases(path)


def test_expect_не_словарь(tmp_path):
    path = write(tmp_path, "- id: a\n  input: x\n  expect: [gym=да]\n")
    with pytest.raises(CaseError, match="набором проверок"):
        load_cases(path)


def test_вложенный_список_это_ошибка(tmp_path):
    path = write(tmp_path, "- id: a\n  input: x\n  expect:\n    contains_none: [[a, b]]\n")
    with pytest.raises(CaseError, match="строка или число"):
        load_cases(path)
