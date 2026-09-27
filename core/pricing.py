"""Цена прогона в долларах. Сами цены и арифметика живут в token-counter.

Здесь только связка: сложить токены по вариантам и разделить две суммы.
«Цена ответов» считает все ответы, в том числе взятые из кэша: это сколько
стоил бы вариант, если спрашивать модель с нуля. «Потрачено сейчас» считает
только ответы, за которые заплатили в этом запуске.

Если модели нет в таблице цен или таблица не читается, прогон не падает:
цена просто неизвестна, и причина видна в отчёте.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from token_counter import PriceError, Usage, cost, estimate_tokens, find_price, format_usd, load_prices

from core.client import MAX_TOKENS


@dataclass(frozen=True)
class VariantCost:
    variant: str
    answers: Decimal  # цена всех полученных ответов, вместе с кэшем
    spent: Decimal    # заплачено в этом запуске, без ответов из кэша


@dataclass
class RunCost:
    model: str
    known: bool
    reason: str | None = None     # почему цена неизвестна
    checked: str | None = None    # дата сверки цены в token-counter
    variants: list[VariantCost] = field(default_factory=list)

    @property
    def answers(self) -> Decimal:
        return sum((v.answers for v in self.variants), Decimal(0))

    @property
    def spent(self) -> Decimal:
        return sum((v.spent for v in self.variants), Decimal(0))

    def for_variant(self, variant: str) -> VariantCost | None:
        return next((v for v in self.variants if v.variant == variant), None)

    def to_json(self) -> dict:
        """Для сохранения рядом с результатами. Деньги строками, чтобы не терять точность."""
        if not self.known:
            return {"model": self.model, "known": False, "reason": self.reason}
        return {
            "model": self.model,
            "known": True,
            "currency": "USD",
            "prices_checked": self.checked,
            "answers_usd": str(self.answers),
            "spent_usd": str(self.spent),
            "variants": [
                {"variant": v.variant, "answers_usd": str(v.answers), "spent_usd": str(v.spent)}
                for v in self.variants
            ],
        }


def _price(model: str, prices_path=None):
    """Цена модели или текст причины, почему её нет. Исключения наружу не выпускает."""
    try:
        return find_price(model, load_prices(prices_path)), None
    except PriceError as err:
        return None, str(err)


def price_run(results, model: str, prices_path=None) -> RunCost:
    """Считает цену каждого варианта по токенам из результатов прогона.

    results это список Result из core.runner. У ответов со сбоем токенов нет
    (ноль), поэтому они ничего не добавляют: неудачный запрос API не оплачивается.
    """
    price, reason = _price(model, prices_path)
    if price is None:
        return RunCost(model=model, known=False, reason=reason)

    order = list(dict.fromkeys(r.variant for r in results))
    variants = []
    for variant in order:
        answers = spent = Decimal(0)
        for r in results:
            if r.variant != variant:
                continue
            usage = Usage(input_tokens=r.input_tokens, output_tokens=r.output_tokens,
                          cache_read_tokens=r.cache_read_tokens)
            try:
                one = cost(usage, price).total
            except PriceError as err:
                # Например, есть токены из кэша промпта, а цены кэша в таблице нет
                return RunCost(model=model, known=False, reason=str(err))
            answers += one
            if not r.cached:
                spent += one
        variants.append(VariantCost(variant, answers, spent))

    return RunCost(model=model, known=True, checked=price.checked, variants=variants)


def estimate_upper(jobs, model: str, prices_path=None, max_tokens: int = MAX_TOKENS):
    """Прикидка сверху для --dry-run: сколько может стоить отправить эти запросы.

    jobs это пары (промпт, вход). Вход прикидывается без токенизатора (с запасом),
    ответ считается как полный max_tokens, потому что длину ответа заранее не знает никто.
    Возвращает (сумма, None) или (None, причина).
    """
    price, reason = _price(model, prices_path)
    if price is None:
        return None, reason
    total = Decimal(0)
    for prompt, user_input in jobs:
        tokens = estimate_tokens(prompt).tokens + estimate_tokens(user_input).tokens
        total += cost(Usage(input_tokens=tokens, output_tokens=max_tokens), price).total
    return total, None


def usd(amount: Decimal) -> str:
    return format_usd(amount)
