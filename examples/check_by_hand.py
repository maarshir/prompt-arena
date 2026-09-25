"""Проверка ответов вручную, пока нет прогона.

Ответы ниже написаны руками, чтобы было видно, как работают проверки.
Запуск из корня репозитория:

    python -m examples.check_by_hand
"""

from core.cases import load_cases
from core.checks import check

answers = {
    "two_facts": "water=0.5; gym=да; sleep=0",
    "gym_no": "Конечно! gym=да",
    "nothing_useful": "Пусто.",
}

cases = {case.id: case for case in load_cases("cases/parse_day.yaml")}

for case_id, answer in answers.items():
    ok = check(answer, cases[case_id].expect)
    print(f"{case_id:15} {'да ' if ok else 'нет'}  {answer}")
