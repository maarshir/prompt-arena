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
        unknown = set(expect) - KNOWN_CHECKS
        if unknown:
            raise CaseError(
                f"Задача {case_id}: неизвестная проверка {sorted(unknown)}"
            )

        cases.append(
            Case(
                id=case_id,
                input=item["input"],
                expect=expect,
                note=item.get("note", ""),
            )
        )

    if not cases:
        raise CaseError("В файле нет ни одной задачи")

    return cases
