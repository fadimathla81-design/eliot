# wave_engine/timeframe_alignment.py

"""
Multi-Timeframe Alignment Engine

المنطق:

1- إذا كان الفريم الأعلى داخل تصحيح ABC:
    - wave_A / wave_C = اتجاه التصحيح النشط
    - wave_B = ارتداد داخل التصحيح

2- إذا كان D1 يتحرك بنفس اتجاه تصحيح W1
   فهذا ليس تعارضاً بل تأكيد للتصحيح.

3- إذا كان H1 يتحرك بنفس اتجاه D1
   فهذا تأكيد إضافي.

4- الفريمات غير الواضحة لا تعتبر تعارضاً كاملاً.
"""


def _get_bias(wave):

    pattern = wave.get("pattern", "")
    current = wave.get("current_wave", "")
    direction = wave.get("direction", "")

    # -------------------------------------------------
    # التصحيحات
    # -------------------------------------------------

    if pattern in ("ABC", "zigzag", "flat"):

        # A أو C = اتجاه التصحيح الفعلي

        if current in ("wave_A", "wave_C"):

            if direction == "up":
                return "bullish_correction"

            if direction == "down":
                return "bearish_correction"

        # B = ارتداد داخل التصحيح

        if current == "wave_B":
            return "corrective"

    # -------------------------------------------------
    # Impulses
    # -------------------------------------------------

    if direction == "up":
        return "bullish"

    if direction == "down":
        return "bearish"

    # fallback

    if "bullish" in pattern:
        return "bullish"

    if "bearish" in pattern:
        return "bearish"

    return "neutral"


def _is_correction_confirmation(parent_bias, child_bias):

    # W1 تصحيح هابط و D1 هابط
    if (
        parent_bias == "bearish_correction"
        and child_bias == "bearish"
    ):
        return True

    # W1 تصحيح صاعد و D1 صاعد
    if (
        parent_bias == "bullish_correction"
        and child_bias == "bullish"
    ):
        return True

    return False


def analyze_alignment(
    weekly_wave,
    daily_wave,
    h1_wave
):

    score = 0
    details = []

    w1_bias = _get_bias(weekly_wave)
    d1_bias = _get_bias(daily_wave)
    h1_bias = _get_bias(h1_wave)

    # =================================================
    # W1 ↔ D1
    # =================================================

    if d1_bias == "neutral":

        score -= 10

        details.append(
            "D1 غير واضح (-10)"
        )

    elif _is_correction_confirmation(
        w1_bias,
        d1_bias
    ):

        score += 30

        details.append(
            "D1 يؤكد تصحيح W1 (+30)"
        )

    elif d1_bias == w1_bias:

        score += 35

        details.append(
            "D1 يؤكد اتجاه W1 (+35)"
        )

    elif d1_bias == "corrective":

        score += 15

        details.append(
            "D1 في ارتداد تصحيحي (+15)"
        )

    else:

        score -= 20

        details.append(
            "D1 يعارض W1 (-20)"
        )

    # =================================================
    # D1 ↔ H1
    # =================================================

    if h1_bias == "neutral":

        score -= 5

        details.append(
            "H1 غير واضح (-5)"
        )

    elif _is_correction_confirmation(
        d1_bias,
        h1_bias
    ):

        score += 20

        details.append(
            "H1 يؤكد تصحيح D1 (+20)"
        )

    elif h1_bias == d1_bias:

        score += 25

        details.append(
            "H1 يؤكد D1 (+25)"
        )

    elif h1_bias == "corrective":

        score += 10

        details.append(
            "H1 في ارتداد داخلي (+10)"
        )

    else:

        score -= 10

        details.append(
            "H1 يعارض D1 (-10)"
        )

    # =================================================
    # مراحل متقدمة
    # =================================================

    if daily_wave.get("current_wave") == "wave_C":

        score += 10

        details.append(
            "D1 في wave_C — نهاية التصحيح محتملة (+10)"
        )

    if h1_wave.get("current_wave") == "wave_C":

        score += 10

        details.append(
            "H1 في wave_C — نهاية التصحيح محتملة (+10)"
        )

    # =================================================
    # ملاحظة على المراحل المبكرة
    # =================================================

    if weekly_wave.get("current_wave") == "wave_A":

        details.append(
            "W1 في wave_A — التصحيح مازال مبكراً"
        )

    # =================================================

    score = max(0, min(score, 100))

    aligned = score >= 60

    return {

        "aligned": aligned,

        "score": score,

        "details": details,

        "biases": {

            "W1": w1_bias,
            "D1": d1_bias,
            "H1": h1_bias

        }
    }