"""Проверка ответов, написанных руками, без модели и без ключа.

Ответы ниже придуманы, чтобы было видно, как работают проверки.
Запуск из корня репозитория:

    python -m examples.check_by_hand
"""

from core.cases import load_cases
from core.checks import check

answers = {
    "order_and_phone": "order=48213; phone=+79161234567",
    "urgent_negated": "Вот поля: order=1204; urgent=yes",
    "two_numbers": "order=12",
    "nothing_useful": "Пусто.",
}

cases = {case.id: case for case in load_cases("cases/support_ticket.yaml")}

for case_id, answer in answers.items():
    ok = check(answer, cases[case_id].expect)
    print(f"{case_id:16} {'да ' if ok else 'нет'}  {answer}")
