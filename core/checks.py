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


def exact(answer: str, expected) -> bool:
    """Точное совпадение после приведения к общему виду.

    Подходит только для коротких ответов: да или нет, число, одно слово.
    Число в ожидании (exact: 5 без кавычек) сравнивается как текст "5".
    """
    return normalize(answer) == normalize(str(expected))


def found(item: str, text: str) -> bool:
    """Есть ли кусок item в тексте text (оба уже нормализованы).

    Обычный поиск подстроки, но число не режется посередине:
    "water=0.3" не находится в "water=0.35", "300" не находится в "1300",
    "5" не находится в "0.5". Слова по-прежнему ищутся как подстрока,
    чтобы "зал" находился в "зале": в русском окончания меняются,
    и граница слова здесь сломала бы больше, чем починила.
    """
    if not item:
        return True
    pattern = re.escape(item)
    if item[0].isdigit():
        # слева не цифра и не "цифра + точка/запятая" (иначе мы внутри дроби)
        pattern = r"(?<!\d)(?<!\d[.,])" + pattern
    if item[-1].isdigit():
        # справа не цифра и не дробная часть
        pattern = pattern + r"(?!\d)(?![.,]\d)"
    return re.search(pattern, text) is not None


def contains_all(answer: str, required: list[str]) -> bool:
    """В ответе есть все ключевые факты.

    Формулировка может быть любой, важно только наличие сути.
    """
    low = normalize(answer)
    return all(found(normalize(str(item)), low) for item in required)


def contains_none(answer: str, forbidden: list[str]) -> bool:
    """В ответе нет ни одного запрещённого куска.

    Главное применение: ловить вежливый мусор вроде "конечно", "вот ответ",
    когда просили только значение.
    """
    low = normalize(answer)
    return not any(found(normalize(str(item)), low) for item in forbidden)


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
