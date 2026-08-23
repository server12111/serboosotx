from decimal import Decimal


def fmt_rub(amount: Decimal) -> str:
    return f"{amount:,.2f}".replace(",", " ").replace(".", ",") + " ₽"


def fmt_qty(quantity: int) -> str:
    return f"{quantity:,}".replace(",", " ")
