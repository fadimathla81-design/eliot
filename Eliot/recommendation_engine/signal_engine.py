# recommendation_engine/signal_engine.py
"""
Signal Engine with Phase-Based Entry Logic

التحديثات:
- شروط دقيقة للإشارات بناءً على phase و subwave
- منع إشارات SELL_NOW/BUY_NOW إذا لم يتأكد BOS على H4 وH1
- ربط الدخول بانتهاء تصحيح D1 + تأكيد هيكلي H4 + زخم H1
- WAIT_REVERSAL_CONFIRMATION بدل SELL_NOW_EARLY عند اكتمال wave_C
"""

from enum import Enum


class Bias(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


def build_signal(
    weekly_bias    : str,
    daily_bias     : str,
    h1_bias        : str,
    confidence     : float,
    weekly_pattern : str | None  = None,
    daily_pattern  : str | None  = None,
    h1_pattern     : str | None  = None,
    weekly_elliott : dict | None = None,
    daily_elliott  : dict | None = None,
    h1_elliott     : dict | None = None,
    conflict_result: dict | None = None,
    bos            : dict | None = None,
    # ✅ جديد: BOS منفصل لـ H4 وH1 وسياق W1/D1
    w1_elliott     : dict | None = None,
    d1_elliott     : dict | None = None,
    h4_bos         : dict | None = None,
    h1_bos         : dict | None = None,
) -> str:

    raw_signal = _build_raw_signal(
        weekly_bias, daily_bias, h1_bias, confidence,
        weekly_pattern, daily_pattern, h1_pattern,
        weekly_elliott, daily_elliott, h1_elliott,
        conflict_result,
        w1_elliott = w1_elliott,
        d1_elliott = d1_elliott,
        h4_bos     = h4_bos,
        h1_bos     = h1_bos,
    )

    from recommendation_engine.conflict_resolver import classify_signal_mode

    immediate_signals = (
        "SELL_NOW", "BUY_NOW", "STRONG_SELL", "STRONG_BUY"
    )

    if raw_signal in immediate_signals and bos is not None:
        base = "SELL_NOW" if "SELL" in raw_signal else "BUY_NOW"
        classification = classify_signal_mode(base, bos)
        if classification["mode"] == "AGGRESSIVE":
            return f"{raw_signal}_EARLY"

    return raw_signal


def _build_raw_signal(
    weekly_bias    : str,
    daily_bias     : str,
    h1_bias        : str,
    confidence     : float,
    weekly_pattern : str | None  = None,
    daily_pattern  : str | None  = None,
    h1_pattern     : str | None  = None,
    weekly_elliott : dict | None = None,
    daily_elliott  : dict | None = None,
    h1_elliott     : dict | None = None,
    conflict_result: dict | None = None,
    w1_elliott     : dict | None = None,
    d1_elliott     : dict | None = None,
    h4_bos         : dict | None = None,
    h1_bos         : dict | None = None,
) -> str:

    # ── فحص H1 Elliott أولاً مع سياق كامل ──────────────────────
    if h1_elliott is not None:
        h1_signal = _evaluate_h1_elliott(
            h1_elliott,
            d1_elliott = d1_elliott,
            w1_elliott = w1_elliott,
            h4_bos     = h4_bos,
            h1_bos     = h1_bos,
        )
        if h1_signal:
            return h1_signal

    # ── المسار القديم: conflict_result ───────────────────────────
    if conflict_result is not None:
        from recommendation_engine.conflict_resolver import get_entry_signal
        return get_entry_signal(
            conflict_result,
            h1_elliott,
            confidence=confidence,
        )

    # ── fallback – bias فقط ───────────────────────────────────────
    if (
        weekly_bias == "bearish"
        and daily_bias == "bearish"
        and h1_bias   == "bearish"
        and confidence >= 75
    ):
        return "STRONG_SELL"

    if (
        weekly_bias == "bearish"
        and daily_bias == "bearish"
        and h1_bias   == "bearish"
    ):
        return "SELL"

    if (
        weekly_pattern == "bearish_impulse"
        and (daily_pattern == "ABC" or h1_pattern == "ABC")
    ):
        return "WAIT_SELL"

    if (
        weekly_bias == "bearish"
        and (daily_bias != "bearish" or h1_bias != "bearish")
    ):
        return "WAIT_SELL"

    if (
        weekly_bias == "bullish"
        and daily_bias == "bullish"
        and h1_bias   == "bullish"
        and confidence >= 75
    ):
        return "STRONG_BUY"

    if (
        weekly_bias == "bullish"
        and daily_bias == "bullish"
        and h1_bias   == "bullish"
    ):
        return "BUY"

    if (
        weekly_pattern == "bullish_impulse"
        and (daily_pattern == "ABC" or h1_pattern == "ABC")
    ):
        return "WAIT_BUY"

    if (
        weekly_bias == "bullish"
        and (daily_bias != "bullish" or h1_bias != "bullish")
    ):
        return "WAIT_BUY"

    return "NO_TRADE"


def _evaluate_h1_elliott(
    h1_elliott : dict,
    d1_elliott : dict | None = None,
    w1_elliott : dict | None = None,
    h4_bos     : dict | None = None,
    h1_bos     : dict | None = None,
) -> str | None:
    """
    قيّم إشارة H1 بناءً على Elliott مع تأكيد هيكلي كامل.

    شروط BUY_NOW (كلها يجب أن تتحقق معاً):
    ✅ H1: phase=correction_completed + wave_C + subwave=wave_5
    ✅ W1: bullish (ABC أو bullish_impulse)
    ✅ D1: wave_C في نهاية التصحيح
    ✅ H4 BOS: bullish (تأكيد هيكلي)
    ✅ H1 BOS: bullish (تأكيد زخمي)

    شروط SELL_NOW (عكس كل ما سبق):
    ✅ H1: phase=correction_completed + wave_C + subwave=wave_5
    ✅ W1: bearish
    ✅ D1: wave_C في نهاية التصحيح الصاعد
    ✅ H4 BOS: bearish
    ✅ H1 BOS: bearish

    إذا اكتمل H1 لكن لم يتأكد BOS:
    → WAIT_REVERSAL_CONFIRMATION (بدل SELL_NOW_EARLY)
    """

    phase        = h1_elliott.get("phase")
    current_wave = h1_elliott.get("current_wave")
    subwave      = h1_elliott.get("subwave")
    confidence   = h1_elliott.get("confidence", 0)

    # ── فحص اكتمال H1 wave_C ─────────────────────────────────────
    h1_completed = (
        phase == "correction_completed"
        and current_wave == "wave_C"
        and subwave == "wave_5"
        and confidence >= 70
    )

    if not h1_completed:
        # التصحيح لا يزال جارياً → WAIT
        if phase == "correction_ongoing" and current_wave in ("wave_A", "wave_B", "wave_C"):
            # حدد الاتجاه من W1
            w1_bullish = _is_w1_bullish(w1_elliott)
            w1_bearish = _is_w1_bearish(w1_elliott)
            if w1_bullish:
                return "WAIT_BUY"
            if w1_bearish:
                return "WAIT_SELL"
        return None

    # ── H1 اكتمل — الآن نحتاج تأكيد هيكلي ──────────────────────

    # فحص W1
    w1_bullish = _is_w1_bullish(w1_elliott)
    w1_bearish = _is_w1_bearish(w1_elliott)

    # فحص D1
    d1_bearish_correction = _is_d1_correction_near_end(d1_elliott, direction="down")
    d1_bullish_correction = _is_d1_correction_near_end(d1_elliott, direction="up")

    # فحص BOS
    h4_bullish_bos = h4_bos is not None and h4_bos.get("direction") == "bullish"
    h4_bearish_bos = h4_bos is not None and h4_bos.get("direction") == "bearish"
    h1_bullish_bos = h1_bos is not None and h1_bos.get("direction") == "bullish"
    h1_bearish_bos = h1_bos is not None and h1_bos.get("direction") == "bearish"

    # ══════════════════════════════════════════════════════════════
    # BUY_NOW: كل الشروط مجتمعة
    # ══════════════════════════════════════════════════════════════
    if (
        w1_bullish
        and d1_bearish_correction   # D1 ينهي تصحيحاً هابطاً
        and h4_bullish_bos          # H4 كسر قمة → تأكيد هيكلي
        and h1_bullish_bos          # H1 كسر قمة → تأكيد زخمي
    ):
        return "BUY_NOW"

    # ══════════════════════════════════════════════════════════════
    # SELL_NOW: كل الشروط مجتمعة
    # ══════════════════════════════════════════════════════════════
    if (
        w1_bearish
        and d1_bullish_correction   # D1 ينهي تصحيحاً صاعداً
        and h4_bearish_bos          # H4 كسر قاع → تأكيد هيكلي
        and h1_bearish_bos          # H1 كسر قاع → تأكيد زخمي
    ):
        return "SELL_NOW"

    # ══════════════════════════════════════════════════════════════
    # H1 اكتمل لكن BOS لم يتأكد بعد
    # بدل SELL_NOW_EARLY → WAIT_REVERSAL_CONFIRMATION
    # ══════════════════════════════════════════════════════════════
    if w1_bullish:
        return "WAIT_REVERSAL_CONFIRMATION_BUY"
    if w1_bearish:
        return "WAIT_REVERSAL_CONFIRMATION_SELL"

    return "WAIT_REVERSAL_CONFIRMATION"


def _is_w1_bullish(w1_elliott: dict | None) -> bool:
    """W1 bullish: ABC أو bullish_impulse مع موجة تصحيحية جارية."""
    if w1_elliott is None:
        return False
    pattern = w1_elliott.get("pattern", "")
    current = w1_elliott.get("current_wave", "")
    return (
        pattern in ("ABC", "bullish_impulse")
        and current in ("wave_A", "wave_B", "wave_C", "wave_1",
                        "wave_2", "wave_3", "wave_4", "wave_5")
    )


def _is_w1_bearish(w1_elliott: dict | None) -> bool:
    """W1 bearish: ABC هابطة أو bearish_impulse."""
    if w1_elliott is None:
        return False
    pattern   = w1_elliott.get("pattern", "")
    direction = w1_elliott.get("direction", "")
    return (
        pattern == "bearish_impulse"
        or (pattern == "ABC" and direction == "down")
    )


def _is_d1_correction_near_end(
    d1_elliott: dict | None,
    direction: str = "down",
) -> bool:
    """
    D1 في نهاية تصحيح:
    - wave_C جارية أو مكتملة
    - next_wave يشير لاستئناف الاتجاه
    """
    if d1_elliott is None:
        return False
    current = d1_elliott.get("current_wave", "")
    phase   = d1_elliott.get("phase", "")
    next_w  = d1_elliott.get("next_wave", "")
    return (
        current == "wave_C"
        and phase in ("correction_ongoing", "correction_completed", "impulse_ongoing")
        and next_w in ("impulse", "trend_resumption", "wave_1")
    )