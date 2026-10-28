from decimal import Decimal, InvalidOperation


def price_alert_kind(mode: str, target: Decimal | None, previous: Decimal | None,
                     current: Decimal | None) -> str | None:
    """Return a price event only for a verified current INR selling observation."""
    if current is None:
        return None
    try:
        current = Decimal(current)
        if not current.is_finite() or current <= 0:
            return None
        if previous is not None:
            previous = Decimal(previous)
            if not previous.is_finite() or previous <= 0:
                previous = None
    except (InvalidOperation, TypeError, ValueError):
        return None
    if mode == "any_drop":
        return "price_drop" if previous is not None and current < previous else None
    if mode == "target_price" and target is not None:
        # A previously observed below-target price stays disarmed even after it ages out.
        return "target_price" if current <= target and (previous is None or previous > target) else None
    return None
