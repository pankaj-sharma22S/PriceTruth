from decimal import Decimal

from app.alert_rules import price_alert_kind


def test_any_drop_only_triggers_for_a_decrease():
    assert price_alert_kind("any_drop", None, Decimal("100"), Decimal("99")) == "price_drop"
    assert price_alert_kind("any_drop", None, Decimal("100"), Decimal("100")) is None
    assert price_alert_kind("any_drop", None, Decimal("100"), Decimal("101")) is None


def test_target_alert_triggers_at_or_below_on_crossing_only():
    target = Decimal("80")
    assert price_alert_kind("target_price", target, Decimal("81"), Decimal("80")) == "target_price"
    assert price_alert_kind("target_price", target, Decimal("90"), Decimal("70")) == "target_price"
    assert price_alert_kind("target_price", target, Decimal("80"), Decimal("70")) is None
    assert price_alert_kind("target_price", target, Decimal("70"), Decimal("70")) is None
    assert price_alert_kind("target_price", target, None, Decimal("80")) == "target_price"
    assert price_alert_kind("target_price", target, Decimal("70"), Decimal("70")) is None
    assert price_alert_kind("target_price", target, Decimal("90"), Decimal("80")) == "target_price"


def test_drop_compares_with_previous_valid_observation_even_when_old():
    assert price_alert_kind("any_drop", None, Decimal("100"), None) is None
    assert price_alert_kind("any_drop", None, Decimal("100"), Decimal("90")) == "price_drop"
    assert price_alert_kind("any_drop", None, Decimal("100"), Decimal("0")) is None
