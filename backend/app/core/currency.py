from decimal import ROUND_HALF_UP, Decimal

DEFAULT_CURRENCY = "KWD"

# Minor-unit decimal places per ISO 4217 -- KWD subdivides into 1000
# fils (3 decimals), unlike most currencies' 2. Extend this dict, don't
# hard-code a decimal count anywhere else.
CURRENCY_DECIMALS: dict[str, int] = {
    "KWD": 3,
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
}


def decimal_places(currency: str = DEFAULT_CURRENCY) -> int:
    return CURRENCY_DECIMALS.get(currency.upper(), 2)


def round_currency(value: Decimal | float | str, currency: str = DEFAULT_CURRENCY) -> Decimal:
    """The one place a money amount gets rounded -- `Decimal` arithmetic
    (never `float`, which can't represent 0.1 exactly and would drift
    across repeated calculations), quantized to the correct number of
    decimal places for the given currency, with a fixed rounding mode so
    the same amount always rounds the same way regardless of caller."""
    places = decimal_places(currency)
    quantum = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
