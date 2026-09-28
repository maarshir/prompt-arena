# promptdiff

[![Тесты](https://github.com/maarshir/promptdiff-/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/maarshir/promptdiff-/actions/workflows/tests.yml)

Прогоняет несколько вариантов промпта на одних и тех же задачах и показывает, где ответы разошлись.

```
$ python run.py --prompts prompts/support_ticket.yaml --cases cases/support_ticket.yaml

вариант       прошло   нет  сбой   токены вх/вых     сек        цена
short          4/7       3     0         1260/84     5.6    $0.00504
rules          7/7       0     0         2310/84     5.6    $0.00819

Расхождения (задача: кто прошёл):
  phone_from_8: short нет, rules да
  urgent_negated: short нет, rules да
  two_numbers: short нет, rules да
```

В этом примере ответы модели написаны вручную, вывод программы настоящий.

## Установка

```bash
git clone https://github.com/maarshir/promptdiff- promptdiff && cd promptdiff
pip install -r requirements.txt
cp .env.example .env
```

В `.env` впишите ключ `GROQ_API_KEY` (бесплатный, [console.groq.com/keys](https://console.groq.com/keys)) или `ANTHROPIC_API_KEY`. Нужен Python 3.10+.

## Запуск

```bash
python run.py --prompts prompts/support_ticket.yaml --cases cases/support_ticket.yaml
```

С флагом `--dry-run` покажет, что уйдёт в модель и сколько это примерно стоит, без запросов. Остальные флаги: `python run.py --help`.

## Свои задачи

Задачи лежат в `cases/`, варианты промпта в `prompts/`:

```yaml
- id: urgent_negated
  input: Не срочно, но подскажите, где сейчас заказ 1204
  expect:
    contains_all: ["urgent=no", "order=1204"]
```

Проверки: `exact`, `contains_all`, `contains_none`. Каждая отвечает да или нет.

## Как устроено

Ответы кэшируются на диске, повторный прогон тех же промптов бесплатный. Сбой сети считается отдельно и не попадает в расхождения. Цена каждого варианта считается через [token-counter](https://github.com/maarshir/token-counter).

Почему сделано именно так: [docs/решения.md](docs/решения.md). Тесты: `pytest`.

Набор вопросов к документам из [doc-answers](https://github.com/maarshir/doc-answers) можно прогнать здесь же.
