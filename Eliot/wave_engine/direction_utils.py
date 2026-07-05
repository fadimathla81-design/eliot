# wave_engine/direction_utils.py
"""
Shared helper for computing a simple trend direction ("up" / "down")
from a list of swings, independent of any pattern classification.

This is intentionally dumb and stable: it just compares the price of
the first and last swing in the given window. It must be the single
source of truth for "direction" used across classify_wave,
detect_correction, and the multi-timeframe orchestrator, so that
parent context is never inferred from a pattern label string again.
"""


# wave_engine/direction_utils.py

def compute_direction(swings, window=None):
    if not swings:
        return None

    points = swings[-window:] if window else swings

    if len(points) < 2:
        return None

    # ✅ الحل الهيكلي: قارن أعلى HIGH بأحدث LOW والعكس
    highs = [s for s in points if s["type"] == "HIGH"]
    lows  = [s for s in points if s["type"] == "LOW"]

    if not highs or not lows:
        # fallback: أول وآخر نقطة
        first_price = points[0]["price"]
        last_price  = points[-1]["price"]
        if last_price == first_price:
            return None
        return "up" if last_price > first_price else "down"

    # آخر HIGH وآخر LOW
    last_high = highs[-1]
    last_low  = lows[-1]

    # أيهما أحدث؟
    if last_high["index"] > last_low["index"]:
        # آخر حركة كانت صعود → لكن نقارن بالهيكل
        # لو آخر LOW أعلى من أول LOW → uptrend
        first_low = lows[0]
        return "up" if last_low["price"] > first_low["price"] else "down"
    else:
        # آخر حركة كانت هبوط
        # لو آخر HIGH أقل من أول HIGH → downtrend
        first_high = highs[0]
        return "down" if last_high["price"] < first_high["price"] else "up"