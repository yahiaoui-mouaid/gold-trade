"""Pure formula tests: no database."""
from decimal import Decimal as D

from hypothesis import given
from hypothesis import strategies as st

from ledger.settlement import Line, fine_weight, round_dinars, settle

weights = st.decimals(min_value=D("0.001"), max_value=D("99999.999"), places=3)
finenesses = st.decimals(min_value=D("0.1"), max_value=D("1000.0"), places=1)
rates = st.decimals(min_value=D("0"), max_value=D("99999.99"), places=2)
monies = st.decimals(min_value=D("0"), max_value=D("9999999.99"), places=2)
origins = st.integers(min_value=1, max_value=4)


def lines():
    received = st.builds(lambda o, g, f: Line("in", o, g, f), origins, weights, finenesses)
    given_gold = st.builds(lambda o, g, f, r: Line("out", o, g, f, 1, r), origins, weights, finenesses, rates)
    return st.lists(st.one_of(received, given_gold), max_size=8)


def test_worked_example_separate_origins():
    result = settle([
        Line("in", 1, D("200.000"), D("999.9")),
        Line("out", 2, D("250.000"), D("750"), category_id=9, facon_rate=D("900")),
    ], money_received=D("200000"), money_given=D("0"))
    assert result.gold == {1: D("-199.98"), 2: D("187.5")}
    assert result.facon_total == D("225000")
    assert result.money_difference == D("25000")


def test_same_origin_nets_in_fine_grams():
    result = settle([
        Line("in", 2, D("200.000"), D("999.9")),
        Line("out", 2, D("250.000"), D("750"), category_id=9, facon_rate=D("0")),
    ], D("0"), D("0"))
    assert result.gold == {2: D("-12.48")}


def test_supplier_purchase_keeps_gold_and_money_apart():
    result = settle([Line("in", 1, D("100.000"), D("999.9"))], D("0"), D("1000000"))
    assert result.gold == {1: D("-99.99")}
    assert result.money_difference == D("1000000")


def test_fine_weight_is_exact_to_seven_places():
    assert fine_weight(D("0.001"), D("999.9")) == D("0.0009999")


def test_halves_round_away_from_zero():
    assert round_dinars(D("2.5")) == D("3")
    assert round_dinars(D("-2.5")) == D("-3")
    assert round_dinars(D("2.4")) == D("2")


@given(lines(), monies, monies)
def test_each_origin_is_given_minus_received(ls, received, paid):
    result = settle(ls, received, paid)
    for origin in {line.origin_id for line in ls}:
        expected = sum(li.fine for li in ls if li.origin_id == origin and li.direction == "out") - sum(
            li.fine for li in ls if li.origin_id == origin and li.direction == "in")
        assert result.gold.get(origin, D(0)) == expected


@given(lines(), monies, monies)
def test_money_difference_is_facon_plus_given_minus_received(ls, received, paid):
    result = settle(ls, received, paid)
    assert result.money_difference == result.facon_total + paid - received


@given(weights, finenesses)
def test_fine_never_exceeds_gross(gross, fineness):
    assert fine_weight(gross, fineness) <= gross
