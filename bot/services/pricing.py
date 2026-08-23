from decimal import ROUND_HALF_UP, Decimal


def compute_price(rate_rub: Decimal, quantity: int, markup_percent: Decimal) -> Decimal:
    """rate_rub = upstream cost per 1000. Returns the charge to the user, rounded to kopeks."""
    raw = rate_rub * (Decimal(1) + markup_percent / Decimal(100)) / Decimal(1000) * Decimal(quantity)
    return raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def compute_upstream_cost(rate_rub: Decimal, quantity: int) -> Decimal:
    return (rate_rub / Decimal(1000) * Decimal(quantity)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
