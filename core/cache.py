"""Кэш ответов модели на диске.

Зачем: прогон стоит денег, а чаще всего меняется не промпт, а проверки
или набор задач. Одинаковый запрос второй раз к модели не уходит,
ответ берётся из файла.

Ключ собирается из всего, от чего зависит ответ: модель, промпт, входной
текст, потолок длины ответа и версия API. Поменялась хоть одна буква в
промпте, значит, другой ключ и новый запрос.

Важно: модель отвечает не всегда одинаково. Кэш намеренно закрепляет
первый полученный ответ, чтобы повторный прогон был воспроизводимым.
Чтобы посмотреть, как модель ведёт себя заново, есть --no-cache.
"""

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, replace
from pathlib import Path

from core.client import API_VERSION, MAX_TOKENS, Answer

# Меняется, если меняется формат записи. Старые записи тогда просто не находятся.
FORMAT = 1


def cache_key(prompt: str, user_input: str, model: str, max_tokens: int = MAX_TOKENS) -> str:
    """Отпечаток запроса. json.dumps со списком, а не склейка строк через разделитель:
    иначе ("a|b", "c") и ("a", "b|c") дали бы один и тот же ключ."""
    raw = json.dumps(
        [FORMAT, API_VERSION, model, max_tokens, prompt, user_input],
        ensure_ascii=False,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class AnswerCache:
    """Каждый ответ в своём файле: <папка>/<первые два знака>/<ключ>.json.

    Один файл на ответ, а не одна общая база: запись одного ответа не может
    испортить остальные, и старые ответы легко удалить руками.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> Answer | None:
        path = self._path(key)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            answer = Answer(**data["answer"])
        except FileNotFoundError:
            return None
        except (OSError, ValueError, TypeError, KeyError):
            # Битый или устаревший файл считаем промахом: спросим модель заново
            # и перезапишем. Падать из-за кэша прогон не должен.
            return None
        return replace(answer, cached=True)

    def put(self, key: str, answer: Answer) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = asdict(answer)
        record["cached"] = False
        data = json.dumps({"key": key, "answer": record}, ensure_ascii=False, indent=2)
        # Пишем во временный файл и переименовываем: если прогон прервать
        # посреди записи, в кэше не останется половины файла.
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(data)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


def with_cache(ask, cache: AnswerCache):
    """Оборачивает функцию вида ask_many(jobs, limit) кэшем.

    Возвращает функцию с той же подписью, поэтому прогону всё равно,
    есть кэш или нет. В модель уходят только промахи, причём одинаковые
    запросы внутри одного прогона отправляются один раз. Ошибки
    в кэш не пишутся: сбой сети не должен запомниться как ответ.
    """

    async def cached_ask(jobs, limit=5):
        keys = [cache_key(prompt, user_input, model) for prompt, user_input, model in jobs]
        out = [cache.get(k) for k in keys]

        missing: dict[str, tuple[str, str, str]] = {}
        for key, job, found in zip(keys, jobs, out):
            if found is None and key not in missing:
                missing[key] = job

        if missing:
            fresh = await ask(list(missing.values()), limit=limit)
            got = dict(zip(missing.keys(), fresh))
            for key, answer in got.items():
                if isinstance(answer, Answer):
                    cache.put(key, answer)
            out = [found if found is not None else got[key] for key, found in zip(keys, out)]

        return out

    return cached_ask
