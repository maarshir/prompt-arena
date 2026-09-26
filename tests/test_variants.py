import pytest

from core.variants import VariantError, load_variants


def write(tmp_path, text):
    path = tmp_path / "prompts.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_настоящий_файл_загружается():
    variants = load_variants("prompts/parse_day.yaml")
    assert [v.id for v in variants] == ["short", "rules"]
    assert all(v.prompt for v in variants)


def test_поля_читаются(tmp_path):
    path = write(tmp_path, "- id: a\n  prompt: |\n    текст\n  note: зачем\n")
    [v] = load_variants(path)
    assert (v.id, v.prompt, v.note) == ("a", "текст", "зачем")


@pytest.mark.parametrize(
    "text, message",
    [
        ("id: a", "список"),
        ("- просто строка", "набор полей"),
        ("- prompt: текст", "нет поля id"),
        ("- id: a\n  prompt: x\n- id: a\n  prompt: y", "уже есть"),
        ("- id: a", "prompt"),
        ("- id: a\n  prompt: '   '", "prompt"),
        ("[]", "ни одного"),
    ],
)
def test_ошибки_в_файле(tmp_path, text, message):
    with pytest.raises(VariantError, match=message):
        load_variants(write(tmp_path, text))


def test_числовой_id_становится_строкой(tmp_path):
    [v] = load_variants(write(tmp_path, "- id: 2\n  prompt: x\n"))
    assert v.id == "2"
