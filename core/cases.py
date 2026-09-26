"""Загрузка набора задач из файла."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml

KNOWN_CHECKS = {"exact", "contains_all", "contains_none"}


class CaseError(ValueError):
    """Файл с задачами составлен неверно."""


@dataclass
class Case:
    id: str
    input: str
    expect: dict = field(default_factory=dict)
    note: str = ""


def _as_text(value, where: str) -> str:
    """Значение из YAML в строку для проверки.

    Числа приводим к тексту: exact: 5 без кавычек значит то же, что exact: "5".
    Логические значения не пропускаем: YAML превращает yes, no, true, off
    без кавычек в True или False, и проверка тихо ждала бы "true" вместо "yes".
    """
    if isinstance(value, bool) or value is None:
        raise CaseError(
            f"{where}: значение {value!r} похоже на yes/no/true/false/null без кавычек, "
            "возьмите его в кавычки"
        )
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value
    raise CaseError(f"{where}: ожидалась строка или число, а не {type(value).__name__}")


def _clean_expect(expect: dict, case_id: str) -> dict:
    """Проверяет типы в expect и приводит значения к строкам."""
    clean = {}
    if "exact" in expect:
        clean["exact"] = _as_text(expect["exact"], f"Задача {case_id}, exact")
    for key in ("contains_all", "contains_none"):
        if key not in expect:
            continue
        items = expect[key]
        if not isinstance(items, list):
            # строка вместо списка перебиралась бы по буквам и почти всегда проходила
            raise CaseError(
                f'Задача {case_id}, {key}: нужен список, например {key}: ["gym=да"]'
            )
        clean[key] = [_as_text(item, f"Задача {case_id}, {key}") for item in items]
    return clean


def load_cases(path: str | Path) -> list[Case]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))

    if not isinstance(raw, list):
        raise CaseError("Файл должен содержать список задач")

    cases = []
    seen = set()

    for i, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise CaseError(f"Задача {i}: ожидался набор полей")

        case_id = item.get("id")
        if not case_id:
            raise CaseError(f"Задача {i}: нет поля id")
        if case_id in seen:
            raise CaseError(f"Задача {case_id}: такой id уже есть")
        seen.add(case_id)

        if not item.get("input"):
            raise CaseError(f"Задача {case_id}: нет поля input")

        expect = item.get("expect") or {}
        if not isinstance(expect, dict):
            raise CaseError(f"Задача {case_id}: expect должен быть набором проверок")
        unknown = set(expect) - KNOWN_CHECKS
        if unknown:
            raise CaseError(
                f"Задача {case_id}: неизвестная проверка {sorted(unknown)}"
            )

        cases.append(
            Case(
                id=case_id,
                input=item["input"],
                expect=_clean_expect(expect, case_id),
                note=item.get("note", ""),
            )
        )

    if not cases:
        raise CaseError("В файле нет ни одной задачи")

    return cases
