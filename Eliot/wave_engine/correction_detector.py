# wave_engine/correction_detector.py

"""
Zigzag/Flat correction detector built on a real correction_start point
(passed in from wave_classifier), not a guessed local window.

يدعم الآن:
- wave_A الجاري
- wave_B الجاري
- wave_C المكتمل

بدلاً من إرجاع unknown إذا لم يكتمل التصحيح بعد.
"""

WAVE_B_MIN_RATIO = 0.382
WAVE_B_MAX_RATIO = 1.00

WAVE_C_MIN_RATIO = 0.618
WAVE_C_MAX_RATIO = 1.80


def _find_wave_end(swings, start_index, want_type):

    """
    Find the next swing after start_index
    whose type == want_type.
    """

    for s in swings:

        if (
            s["index"] > start_index
            and
            s["type"] == want_type
        ):

            return s

    return None


def detect_correction(
    swings,
    parent_pattern=None,
    correction_start=None
):

    """
    Detect correction type starting from correction_start.

    Returns:

    wave_A -> correction started but B not formed yet

    wave_B -> A complete, B running

    wave_C -> full ABC complete
    """

    if not correction_start or not swings:

        return {
            "correction_type": "unknown",
            "confidence": 0
        }

    start_idx = correction_start["index"]
    start_price = correction_start["price"]
    start_type = correction_start["type"]

    # ---------------------------------
    # WAVE A
    # ---------------------------------

    a_end_type = (
        "HIGH"
        if start_type == "LOW"
        else "LOW"
    )

    a_end = _find_wave_end(
        swings,
        start_idx,
        a_end_type
    )

    if not a_end:

        return {
            "correction_type": "ABC",
            "current_wave": "wave_A",
            "next_expected": "wave_B",
            "subwave": None,
            "confidence": 70
        }

    # ---------------------------------
    # WAVE B
    # ---------------------------------

    b_end_type = start_type

    b_end = _find_wave_end(
        swings,
        a_end["index"],
        b_end_type
    )

    # لا يوجد B بعد → نحن داخل A

    if not b_end:

        return {
            "correction_type": "ABC",
            "current_wave": "wave_A",
            "next_expected": "wave_B",
            "subwave": None,
            "confidence": 75
        }

    # ---------------------------------
    # WAVE C
    # ---------------------------------

    c_end_type = a_end_type

    c_end = _find_wave_end(
        swings,
        b_end["index"],
        c_end_type
    )

    # لا يوجد C → نحن داخل B

    if not c_end:

        return {
            "correction_type": "ABC",
            "current_wave": "wave_B",
            "next_expected": "wave_C",
            "subwave": None,
            "confidence": 75
        }

    # ---------------------------------
    # VALIDATE RATIOS
    # ---------------------------------

    a_len = abs(
        a_end["price"] - start_price
    )

    b_len = abs(
        b_end["price"] - a_end["price"]
    )

    c_len = abs(
        c_end["price"] - b_end["price"]
    )

    if a_len == 0:

        return {
            "correction_type": "unknown",
            "confidence": 0
        }

    b_ratio = b_len / a_len
    c_ratio = c_len / a_len

    b_valid = (
        b_ratio <= WAVE_B_MAX_RATIO
    )

    c_valid = (
        WAVE_C_MIN_RATIO
        <= c_ratio
        <= WAVE_C_MAX_RATIO
    )

    if not (b_valid and c_valid):

        return {
            "correction_type": "ABC",
            "current_wave": "wave_C",
            "next_expected": "impulse",
            "subwave": None,
            "confidence": 65
        }

    confidence = 80

    if b_ratio < WAVE_B_MIN_RATIO:

        confidence -= 10

    return {

        "correction_type": "ABC",

        "current_wave": "wave_C",

        "next_expected": "impulse",

        "subwave": "wave_5",

        "confidence": confidence,

        "ratios": {

            "b_ratio": round(
                b_ratio,
                4
            ),

            "c_ratio": round(
                c_ratio,
                4
            )
        }
    }