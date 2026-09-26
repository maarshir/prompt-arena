"""Загрузка вариантов промпта из файла."""

from dataclasses import dataclass
from pathlib import Path

import yaml


class VariantError(ValueError):
    """Файл с вариантами составлен неверно."""


@dataclass
class Variant:
    id: str
    prompt: str
    note: str = ""


def load_variants(path: str | Path) -> list[Variant]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))

    if not isinstance(raw, list):
        raise VariantError("Файл должен содержать список вариантов")

    variants = []
    seen = set()

    for i, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise VariantError(f"Вариант {i}: ожидался набор полей")

        variant_id = item.get("id")
        if not variant_id:
            raise VariantError(f"Вариант {i}: нет поля id")
        variant_id = str(variant_id)
        if variant_id in seen:
            raise VariantError(f"Вариант {variant_id}: такой id уже есть")
        seen.add(variant_id)

        prompt = item.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise VariantError(f"Вариант {variant_id}: нет текста в поле prompt")

        variants.append(
            Variant(id=variant_id, prompt=prompt.strip(), note=item.get("note", ""))
        )

    # Сравнивать один вариант не с чем. Но запретить это нельзя:
    # иногда нужно просто прогнать один промпт по задачам. Поэтому только пусто — ошибка.
    if not variants:
        raise VariantError("В файле нет ни одного варианта")

    return variants
