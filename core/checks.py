"""Проверки ответа: как понять, что модель ответил верно.

Каждая проверка возвращает True или False. Никаких оценок от 0 до 1:
размытые оценки прячут проблемы, чёткое да или нет заставляет честно описать ожидание.
"""

import re


def normalize(text: str) -> str:
    """Убирает различия, которые нам неважны: регистр, лишние пробелы, точка в конце."""
    text = text.strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text.rstrip(".!")


def exact(answer: str, expected: str) -> bool:
    """Точное совпадение после приведения к общему виду.

    Подходит только для коротких ответов: да или нет, число, одно слово.
    """
    return normalize(answer) == normalize(expected)


def contains_all(answer: str, required: list[str]) -> bool:
    """В ответе есть все ключевые факты.

    Формулировка может быть любой, важно только наличие сути.
    """
    low = normalize(answer)
    return all(normalize(item) in low for item in required)


def contains_none(answer: str, forbidden: list[str]) -> bool:
    """В ответе нет ни одного запрещённого куска.

    Главное применение: ловить вежливый мусор вроде "конечно", "вот ответ",
    когда просили только значение.
    """
    low = normalize(answer)
    return not any(normalize(item) in low for item in forbidden)


def check(answer: str, expect: dict) -> bool:
    """Применяет все условия из описания задачи. Пустое описание ничего не проверяет.

    expect может содержать ключи: exact, contains_all, contains_none.
    Все указанные должны выполниться одновременно.
    """
    if not expect:
        return True

    if "exact" in expect and not exact(answer, expect["exact"]):
        return False
    if "contains_all" in expect and not contains_all(answer, expect["contains_all"]):
        return False
    if "contains_none" in expect and not contains_none(answer, expect["contains_none"]):
        return False

    return True
