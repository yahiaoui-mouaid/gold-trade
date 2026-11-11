"""The settlement formulas (docs/design-changes.md, section 1).

Pure functions on exact decimals. Positive means the party owes the shop.
"""
from collections import defaultdict
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal(0)


@dataclass(frozen=True)
class Line:
    direction: str  # "in" (received by the shop) or "out" (given by the shop)
    origin_id: int
    gross: Decimal
    fineness: Decimal
    category_id: int | None = None
    facon_rate: Decimal | None = None

    @property
    def fine(self):
        return fine_weight(self.gross, self.fineness)


@dataclass(frozen=True)
class Settlement:
    gold: dict  # origin_id -> difference in fine grams (non-zero only)
    facon_total: Decimal
    money_difference: Decimal


def fine_weight(gross, fineness):
    return gross * fineness / Decimal(1000)


def round_dinars(value):
    # ROUND_HALF_UP in decimal means halves go away from zero, for both signs.
    return value.quantize(Decimal(1), rounding=ROUND_HALF_UP)


def settle(lines, money_received, money_given):
    gold = defaultdict(lambda: ZERO)
    facon_raw = ZERO
    for line in lines:
        if line.direction == "out":
            gold[line.origin_id] += line.fine
            if line.facon_rate is not None:
                facon_raw += line.facon_rate * line.gross
        else:
            gold[line.origin_id] -= line.fine
    facon_total = round_dinars(facon_raw)
    return Settlement(
        gold={origin: diff for origin, diff in gold.items() if diff != ZERO},
        facon_total=facon_total,
        money_difference=facon_total + money_given - money_received,
    )
