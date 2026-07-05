# wave_engine/wave_classifier.py
"""
Wave classification with direction-aware context.

CHANGE LOG (this revision):
- classify_wave now accepts `parent_direction` ("up" | "down" | None)
  IN ADDITION TO `parent_pattern`.
- The decision of "is this impulse actually a correction relative to
  the parent" is now made by comparing the candidate's own implied
  direction against `parent_direction`, NOT by string-matching
  parent_pattern against the literal "bearish_impulse" / "bullish_impulse".
  This fixes the bug where a parent that is itself a correction
  (e.g. "zigzag", "flat", "ABC") was silently ignored because the old
  code only recognized the two impulse labels.
- parent_pattern is still accepted and still used (e.g. to decide
  confidence weighting), but it is no longer load-bearing for the
  direction check.
- When the branch resolves to "ABC" (a correction relative to parent),
  we still compute correction_start the same way as before: search
  backwards through `swings` (not just the local 5-point window) for
  the genuine reversal point in the direction opposite to parent_direction.

NEW (this revision):
- detect_parabolic_move() added to identify extreme spike moves
  (e.g. Silver's 14→121 move) that break normal Elliott ratios.
- When W1 has no parent_direction AND a parabolic move is detected,
  we classify the post-peak collapse as ABC wave_A instead of returning
  "unknown". This prevents the W1=unknown conflict that blocks signals
  on affected instruments (e.g. XAGUSD).

NEW (الخطوة الأولى من مشروع الأنماط المعقدة — Zigzag):
- بعد أن يحدد المنطق الحالي أن التصحيح هو "ABC" ولديه correction_start
  فعلي، نمرّر correction_start هذا لـ detect_zigzag (من
  complex_correction_detector.py) لنرى هل هذا التصحيح هو فعلياً Zigzag
  حقيقي (حيث A وC أنفسهما تركيبتان من 5 موجات دفعية صحيحة)، وهو شكل
  أكثر تشدداً وتحديداً من ABC البسيط الحالي.

NEW (الخطوة الثالثة — Flat):
- إذا فشل Zigzag، نجرّب detect_flat (موجة A تصحيحية بسيطة 3 نقاط،
  موجة B ترتد بنسبة قريبة من 100% من A، موجة C دفعية 5 نقاط). الترتيب
  دائماً: Zigzag أولاً (أكثر تشدداً)، ثم Flat، ثم fallback لـ ABC
  البسيط — نفس فلسفة fail-strict-first في كل خطوة.
  هذا integration معزول وقابل للتراجع: أي خطأ مستقبلي في detect_zigzag
  أو detect_flat لا يكسر تصنيف ABC الأساسي، لأنه fallback آمن دائماً.
"""

from wave_engine.direction_utils import compute_direction
from wave_engine.complex_correction_detector import (
    detect_zigzag, detect_flat, detect_triangle, detect_wxy,
)

CORRECTION_SEARCH_WINDOW = 15
PARABOLIC_THRESHOLD = 1.5   # max/min ratio في الـ swings يعتبر parabolic
PARABOLIC_COLLAPSE = 0.85   # إذا آخر سعر < قمة × هذه النسبة = انهيار مؤكد


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_correction_start(swings, parent_direction):
    """
    Walk backwards through swings to find the real start of the
    correction: the most extreme point in the direction of the
    parent's impulse, within a bounded lookback window.

    If parent_direction == "down": the parent impulse moved price down,
    so the correction starts at the lowest LOW in the lookback window
    (the bottom of that down move).

    If parent_direction == "up": correction starts at the highest HIGH
    in the lookback window.
    """
    if not swings or parent_direction not in ("up", "down"):
        return None

    window = swings[-CORRECTION_SEARCH_WINDOW:]

    if parent_direction == "down":
        candidates = [s for s in window if s["type"] == "LOW"]
        if not candidates:
            return None
        return min(candidates, key=lambda s: s["price"])
    else:
        candidates = [s for s in window if s["type"] == "HIGH"]
        if not candidates:
            return None
        return max(candidates, key=lambda s: s["price"])


def detect_parabolic_move(swings, threshold=PARABOLIC_THRESHOLD):
    """
    كشف الحركات الـ Parabolic التي تكسر نسب Elliott الطبيعية.

    تُعتبر الحركة parabolic إذا كانت نسبة (أعلى سعر / أدنى سعر)
    في جميع الـ swings أكبر من threshold (افتراضي 1.5 أي 150%).

    مثال: XAGUSD ارتفع من ~14$ إلى ~121$ → النسبة ~8.6x → parabolic.

    Args:
        swings: قائمة كاملة من الـ swing dicts
        threshold: الحد الأدنى للنسبة لاعتبار الحركة parabolic

    Returns:
        bool
    """
    if not swings:
        return False

    prices = [s["price"] for s in swings]
    min_p = min(prices)
    max_p = max(prices)

    if min_p <= 0:
        return False

    return (max_p / min_p) > threshold


def _try_upgrade_to_zigzag(swings: list, abc_result: dict) -> dict:
    """
    NEW (مشروع الأنماط المعقدة، خطوة بخطوة — هذه آخر خطوة):
    يحاول ترقية نتيجة ABC بسيطة إلى نمط معقد مفحوص البنية الداخلية،
    بترتيب fail-strict-first: Zigzag أولاً (الأكثر تشدداً: A وC دفعيتان
    بالكامل)، ثم Flat (A تصحيحية بسيطة، B تقترب من 100% من A، C دفعية)،
    ثم Triangle (5 موجات A-E، انكماش متتالي في المدى)، ثم WXY (تركيبة
    Zigzag-X-Zigzag، أي تصحيحان كاملان مربوطان بموجة X). إذا فشلت
    الأربعة، نُبقي على نتيجة ABC الأصلية دون أي تغيير.

    ترتيب WXY في النهاية مقصود: WXY يعتمد داخلياً على نجاح detect_zigzag
    مرتين (لـW ولـY)، فهو أكثر تركيباً وتحديداً من الأنماط الثلاثة
    الأبسط — يُفحص فقط بعد استبعادها، اتساقاً مع نفس فلسفة
    fail-strict-first (الأبسط أولاً، الأكثر تركيباً كاحتمال أخير).

    لا يُستدعى إلا على نتائج pattern=="ABC" مع correction_start فعلي
    (الحالة الوحيدة التي قد تكون فيها نمط معقد حقيقي مخفياً خلف
    تصنيف ABC المبسّط).

    Args:
        swings: التسلسل الكامل لـ swings لهذا التايم فريم.
        abc_result: نتيجة classify_wave الحالية (قبل أي تعديل)،
                    يجب أن تحتوي على pattern=="ABC" وcorrection_start.

    Returns:
        نتيجة محوّلة لنفس بنية مفاتيح ABC (pattern, wave, confidence,
        correction_start) إذا نجح أي فحص صارم، وإلا نفس abc_result
        دون أي تغيير.
    """
    correction_start = abc_result.get("correction_start")
    if abc_result.get("pattern") != "ABC" or not correction_start:
        return abc_result

    # المحاولة الأولى: Zigzag (الأكثر تشدداً)
    zigzag_result = detect_zigzag(swings, correction_start)
    if zigzag_result.get("pattern") == "zigzag":
        return _convert_complex_result(zigzag_result, correction_start, abc_result)

    # المحاولة الثانية: Flat
    flat_result = detect_flat(swings, correction_start)
    if flat_result.get("pattern") == "flat":
        return _convert_complex_result(flat_result, correction_start, abc_result)

    # المحاولة الثالثة: Triangle (5 موجات، فحص مختلف بالكامل عن الأعلى)
    triangle_result = detect_triangle(swings, correction_start)
    if triangle_result.get("pattern") == "triangle":
        return _convert_complex_result(triangle_result, correction_start, abc_result)

    # المحاولة الرابعة والأخيرة: WXY (Zigzag-X-Zigzag، أكثر تركيباً)
    wxy_result = detect_wxy(swings, correction_start)
    if wxy_result.get("pattern") == "wxy":
        return _convert_complex_result(wxy_result, correction_start, abc_result)

    # فشلت الأربعة — نُبقي على ABC الأصلية كما هي تماماً
    return abc_result


def _convert_complex_result(complex_result: dict, correction_start: dict, abc_result: dict) -> dict:
    """
    يحوّل نتيجة من detect_zigzag/detect_flat/detect_triangle/detect_wxy
    (بنية current_wave/next_expected) لنفس بنية مفاتيح classify_wave
    المتوقعة من بقية النظام (wave_classifier يُرجع "wave"، لا
    "current_wave").

    ملاحظة Triangle: current_wave قد يكون wave_D أو wave_E.
    ملاحظة WXY: current_wave قد يكون wave_W/wave_X/wave_Y (تسميات
    جديدة بالكامل، خاصة بهذا التركيب). الخريطة صريحة لكل القيم
    المحتملة بدل الاعتماد على fallback ضمني.
    """
    current_wave = complex_result.get("current_wave")
    wave_map = {
        "wave_A": "wave_A", "wave_B": "wave_B", "wave_C": "wave_C",
        "wave_D": "wave_D", "wave_E": "wave_E",
        "wave_W": "wave_W", "wave_X": "wave_X", "wave_Y": "wave_Y",
    }

    return {
        "pattern": complex_result.get("pattern"),
        "wave": wave_map.get(current_wave, current_wave),
        "confidence": complex_result.get("confidence", abc_result.get("confidence", 0)),
        "correction_start": correction_start,
        # معلومات إضافية للتشخيص — لا تكسر أي مستدعٍ حالي لأنها مفاتيح جديدة
        "zigzag_detail": complex_result,
    }


def _classify_w1_no_parent(swings):
    """
    تصنيف خاص لـ W1 (أو أي TF بدون parent_direction).

    المنطق:
    1. إذا كانت الحركة parabolic وحدث انهيار بعد القمة → ABC wave_A
    2. إذا كانت الحركة parabolic ولا يزال قريباً من القمة → bullish_impulse
    3. إذا لم تكن parabolic → impulse عادي بناءً على الاتجاه العام
    """
    if not swings:
        return {
            "pattern": "unknown",
            "wave": "unknown",
            "confidence": 0,
            "correction_start": None,
        }

    first_price = swings[0]["price"]
    last_price  = swings[-1]["price"]
    inferred_direction = "up" if last_price > first_price else "down"

    is_parabolic = detect_parabolic_move(swings)

    if is_parabolic:
        prices   = [s["price"] for s in swings]
        max_price = max(prices)
        max_swing = max(swings, key=lambda s: s["price"])

        # إذا آخر سعر انهار بأكثر من PARABOLIC_COLLAPSE من القمة
        if last_price < max_price * PARABOLIC_COLLAPSE:
            result = {
                "pattern": "ABC",
                "wave": "wave_A",
                "confidence": 65,
                "correction_start": max_swing,
            }
            return _try_upgrade_to_zigzag(swings, result)
        else:
            # لا يزال قريباً من القمة → impulse صاعد
            return {
                "pattern": "bullish_impulse",
                "wave": "wave_3_or_5",
                "confidence": 60,
                "correction_start": None,
            }

    # حركة عادية (غير parabolic) بدون parent
    pattern = (
        "bullish_impulse" if inferred_direction == "up" else "bearish_impulse"
    )
    return {
        "pattern": pattern,
        "wave": "wave_3_or_5",
        "confidence": 60,
        "correction_start": None,
    }


# ---------------------------------------------------------------------------
# Main classifier
# ---------------------------------------------------------------------------

def classify_wave(swings, parent_pattern=None, parent_direction=None):
    """
    Classify the most recent wave structure in `swings`.

    Args:
        swings: full chronological list of swing dicts for this timeframe
        parent_pattern: pattern label of the higher timeframe (for
            confidence weighting / diagnostics only)
        parent_direction: "up" | "down" | None — the higher timeframe's
            actual price direction. This is what we use to decide
            whether the current candidate is a correction.

    Returns:
        dict with at least: pattern, wave/current_wave, confidence,
        and (when pattern == "ABC" or "zigzag") correction_start.
    """

    if len(swings) < 5:
        return {
            "pattern": "unknown",
            "wave": "unknown",
            "confidence": 0,
            "correction_start": None,
        }

    # -----------------------------------------------------------------------
    # W1 / أعلى TF: لا يوجد parent_direction → مسار خاص
    # -----------------------------------------------------------------------
    if parent_direction is None:
        return _classify_w1_no_parent(swings)

    # -----------------------------------------------------------------------
    # التايم فريمات الأقل: لدينا parent_direction
    # -----------------------------------------------------------------------
    recent = swings[-5:]
    p1 = recent[0]["price"]
    p2 = recent[1]["price"]
    p3 = recent[2]["price"]
    p4 = recent[3]["price"]
    p5 = recent[4]["price"]

    own_direction = "up" if p5 > p1 else ("down" if p5 < p1 else None)

    # ---- Bearish candidate (p3 < p1 and p5 < p3) ----
    if p3 < p1 and p5 < p3:
        if parent_direction == "up" and own_direction == "down":
            # حركة عكس الـ parent → تصحيح ABC
            correction_start = _find_correction_start(swings, parent_direction)
            result = {
                "pattern": "ABC",
                "wave": "wave_C",
                "confidence": 70,
                "correction_start": correction_start,
            }
            return _try_upgrade_to_zigzag(swings, result)
        return {
            "pattern": "bearish_impulse",
            "wave": "wave_3_or_5",
            "confidence": 75,
            "correction_start": None,
        }

    # ---- Bullish candidate (p3 > p1 and p5 > p3) ----
    if p3 > p1 and p5 > p3:
        if parent_direction == "down" and own_direction == "up":
            # حركة عكس الـ parent → تصحيح ABC
            correction_start = _find_correction_start(swings, parent_direction)
            result = {
                "pattern": "ABC",
                "wave": "wave_C",
                "confidence": 70,
                "correction_start": correction_start,
            }
            return _try_upgrade_to_zigzag(swings, result)
        return {
            "pattern": "bullish_impulse",
            "wave": "wave_3_or_5",
            "confidence": 75,
            "correction_start": None,
        }

    # ---- Fallback: شكل غامض ----
    correction_start = _find_correction_start(swings, parent_direction)
    result = {
        "pattern": "ABC",
        "wave": "wave_C",
        "confidence": 65,
        "correction_start": correction_start,
    }
    return _try_upgrade_to_zigzag(swings, result)