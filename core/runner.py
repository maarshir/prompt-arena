"""Прогон: каждый вариант промпта по каждой задаче, проверка ответов, итоги."""

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from core.cases import Case
from core.checks import check
from core.client import ask_many
from core.variants import Variant


@dataclass
class Result:
    variant: str
    case: str
    passed: bool
    answer: str | None = None
    error: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    attempts: int = 0
    seconds: float = 0.0
    cached: bool = False


async def run(
    variants: list[Variant],
    cases: list[Case],
    model: str,
    limit: int = 5,
    ask=ask_many,
) -> list[Result]:
    """Задаёт модели все пары вариант × задача и проверяет ответы.

    ask подменяется в тестах, чтобы не ходить в сеть.
    Порядок результатов тот же, что у пар: сначала все задачи первого варианта.
    """
    pairs = [(v, c) for v in variants for c in cases]
    jobs = [(v.prompt, c.input, model) for v, c in pairs]
    answers = await ask(jobs, limit=limit)

    results = []
    for (variant, case), answer in zip(pairs, answers):
        if isinstance(answer, BaseException):
            # Нет ответа — задача не пройдена, но причину пишем отдельно,
            # чтобы в итогах сбой сети не выглядел как ошибка промпта.
            results.append(
                Result(variant.id, case.id, passed=False, error=str(answer) or type(answer).__name__)
            )
            continue

        results.append(
            Result(
                variant=variant.id,
                case=case.id,
                passed=check(answer.text, case.expect),
                answer=answer.text,
                input_tokens=answer.input_tokens,
                output_tokens=answer.output_tokens,
                attempts=answer.attempts,
                seconds=answer.seconds,
                cached=answer.cached,
            )
        )

    return results


@dataclass
class VariantSummary:
    variant: str
    passed: int
    failed: int
    errors: int
    input_tokens: int
    output_tokens: int
    seconds: float
    # Сколько ответов взято из кэша. Токены и время у них из того прогона,
    # где ответ был получен: это цена ответа, а не траты этого запуска.
    cached: int = 0


def summarize(results: list[Result]) -> list[VariantSummary]:
    """Итоги по каждому варианту в том порядке, в каком варианты шли в прогоне."""
    order = list(dict.fromkeys(r.variant for r in results))
    summary = []
    for variant in order:
        rows = [r for r in results if r.variant == variant]
        summary.append(
            VariantSummary(
                variant=variant,
                passed=sum(r.passed for r in rows),
                failed=sum(not r.passed and r.error is None for r in rows),
                errors=sum(r.error is not None for r in rows),
                input_tokens=sum(r.input_tokens for r in rows),
                output_tokens=sum(r.output_tokens for r in rows),
                seconds=round(sum(r.seconds for r in rows), 3),
                cached=sum(r.cached for r in rows),
            )
        )
    return summary


def disagreements(results: list[Result]) -> dict[str, dict[str, bool]]:
    """Задачи, где варианты разошлись: хотя бы один прошёл и хотя бы один нет.

    Задачи, где у кого-то сбой вместо ответа, сюда не попадают:
    про них нельзя сказать, что варианты разошлись, ответа просто нет.
    Возвращает {задача: {вариант: прошёл ли}} в порядке задач.
    """
    by_case: dict[str, dict[str, bool]] = {}
    broken = set()
    for r in results:
        by_case.setdefault(r.case, {})[r.variant] = r.passed
        if r.error is not None:
            broken.add(r.case)

    return {
        case: marks
        for case, marks in by_case.items()
        if case not in broken and len(set(marks.values())) > 1
    }


def save(results: list[Result], path: str | Path, meta: dict) -> Path:
    """Пишет прогон в JSON: условия прогона и все ответы как есть.

    Ответы сохраняются целиком, чтобы потом можно было перепроверить их
    новыми проверками без повторных запросов к модели.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "meta": {"saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **meta},
        "summary": [asdict(s) for s in summarize(results)],
        "results": [asdict(r) for r in results],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
