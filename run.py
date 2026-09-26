"""Прогон вариантов промпта по набору задач.

Пример:

    python run.py --prompts prompts/parse_day.yaml --cases cases/parse_day.yaml

Без ключа можно посмотреть, что будет отправлено: добавьте --dry-run.
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

from core.cache import AnswerCache, cache_key, with_cache
from core.cases import load_cases
from core.client import ask_many
from core.runner import disagreements, run, save, summarize
from core.variants import load_variants

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_CACHE = ".cache/answers"


def load_env(path: str | Path = ".env") -> None:
    """Читает простой файл KEY=VALUE. Уже заданные переменные не трогает.

    Отдельная библиотека ради десяти строк не нужна.
    """
    path = Path(path)
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Сравнение вариантов промпта на наборе задач")
    p.add_argument("--prompts", required=True, help="YAML с вариантами промпта")
    p.add_argument("--cases", required=True, help="YAML с задачами")
    p.add_argument("--model", default=None, help=f"модель (по умолчанию ARENA_MODEL или {DEFAULT_MODEL})")
    p.add_argument("--limit", type=int, default=5, help="сколько запросов одновременно")
    p.add_argument("--out", default=None, help="куда сохранить результаты (JSON)")
    p.add_argument("--dry-run", action="store_true", help="только показать, что будет отправлено")
    p.add_argument("--no-cache", action="store_true", help="не брать ответы из кэша и не сохранять их туда")
    p.add_argument("--cache-dir", default=DEFAULT_CACHE, help=f"папка кэша ответов (по умолчанию {DEFAULT_CACHE})")
    return p.parse_args(argv)


def print_report(results) -> None:
    print()
    print(f"{'вариант':12} {'прошло':>7} {'нет':>5} {'сбой':>5} {'токены вх/вых':>15} {'сек':>7}")
    for s in summarize(results):
        total = s.passed + s.failed + s.errors
        tokens = f"{s.input_tokens}/{s.output_tokens}"
        print(f"{s.variant:12} {s.passed:>3}/{total:<3} {s.failed:>5} {s.errors:>5} {tokens:>15} {s.seconds:>7}")

    diff = disagreements(results)
    print()
    if not diff:
        print("Расхождений нет: на каждой задаче варианты ответили одинаково по итогу проверок.")
    else:
        print("Расхождения (задача: кто прошёл):")
        for case, marks in diff.items():
            line = ", ".join(f"{v} {'да' if ok else 'нет'}" for v, ok in marks.items())
            print(f"  {case}: {line}")

    cached = sum(r.cached for r in results)
    if cached:
        print()
        print(f"Из кэша: {cached} из {len(results)} ответов, за них в этот раз не платили. "
              "Чтобы спросить модель заново, добавьте --no-cache.")

    errors = [r for r in results if r.error]
    if errors:
        print()
        print("Сбои (ответа нет, промпт тут ни при чём):")
        for r in errors:
            print(f"  {r.variant} / {r.case}: {r.error[:120]}")


def main(argv=None) -> int:
    load_env()
    args = parse_args(argv)
    model = args.model or os.environ.get("ARENA_MODEL") or DEFAULT_MODEL

    variants = load_variants(args.prompts)
    cases = load_cases(args.cases)
    total = len(variants) * len(cases)

    cache = None if args.no_cache else AnswerCache(args.cache_dir)
    print(f"Вариантов: {len(variants)}, задач: {len(cases)}, запросов: {total}, модель: {model}")
    if cache is not None:
        keys = {cache_key(v.prompt, c.input, model) for v in variants for c in cases}
        hits = sum(cache.get(k) is not None for k in keys)
        print(f"В кэше уже есть ответов: {hits}, пойдёт в модель: {len(keys) - hits}")

    if args.dry_run:
        for v in variants:
            print(f"\n--- {v.id} ---\n{v.prompt}")
        print(f"\nЗадачи: {', '.join(c.id for c in cases)}")
        return 0

    if not os.environ.get("ANTHROPIC_API_KEY") and not (cache is not None and hits == len(keys)):
        # Проверяем до прогона: иначе получим столько же одинаковых ошибок, сколько запросов.
        # Если все ответы уже в кэше, ключ не нужен: можно перепроверить старые ответы.
        print("Не задан ANTHROPIC_API_KEY. Скопируйте .env.example в .env и впишите ключ.", file=sys.stderr)
        return 2

    ask = ask_many if cache is None else with_cache(ask_many, cache)
    results = asyncio.run(run(variants, cases, model, limit=args.limit, ask=ask))

    out = args.out or f"results/{datetime.now():%Y-%m-%d_%H-%M}_{Path(args.cases).stem}.json"
    save(results, out, {"model": model, "prompts": args.prompts, "cases": args.cases, "cache": cache is not None})

    print_report(results)
    print(f"\nВсе ответы сохранены в {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
