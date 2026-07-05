# correction_completion_engine.py


def detect_correction_completion(tf_data):

    """
    Determines whether an Elliott correction
    is likely completed.

    Returns:
    {
        "completed": bool,
        "score": int,
        "reasons": list,
        "bos_confirmed": bool,
        "choch_confirmed": bool
    }
    """

    score = 0
    reasons = []

    elliott = tf_data.get("elliott", {})
    pivots = tf_data.get("pivots", {})

    highs = pivots.get("highs", [])
    lows = pivots.get("lows", [])

    current_wave = elliott.get("current_wave")
    next_wave = elliott.get("next_wave")
    phase = elliott.get("phase")

    # ==================================================
    # 1) Elliott completion check
    # ==================================================

    if (
        current_wave == "wave_C"
        and next_wave in [
            "impulse",
            "trend_resumption"
        ]
    ):

        score += 30

        reasons.append(
            "Elliott suggests correction completion"
        )

    if phase == "correction_completed":

        score += 15

        reasons.append(
            "Phase marked as correction_completed"
        )

    # ==================================================
    # 2) Bullish BOS detection
    # ==================================================

    bos_confirmed = False

    if len(highs) >= 2:

        last_high = highs[-1]["price"]
        previous_high = highs[-2]["price"]

        if last_high > previous_high:

            bos_confirmed = True

            score += 25

            reasons.append(
                "Bullish BOS confirmed"
            )

    # ==================================================
    # 3) CHOCH detection
    # ==================================================

    choch_confirmed = False

    if len(highs) >= 2 and len(lows) >= 2:

        last_high = highs[-1]["price"]
        previous_high = highs[-2]["price"]

        last_low = lows[-1]["price"]
        previous_low = lows[-2]["price"]

        higher_high = last_high > previous_high
        higher_low = last_low > previous_low

        if higher_high and higher_low:

            choch_confirmed = True

            score += 20

            reasons.append(
                "Bullish CHOCH confirmed"
            )

    # ==================================================
    # 4) Strong momentum confirmation
    # ==================================================

    if bos_confirmed and choch_confirmed:

        score += 10

        reasons.append(
            "Structure fully reversed"
        )

    # ==================================================
    # 5) Final decision
    # ==================================================

    completed = score >= 70

    return {

        "completed": completed,

        "score": min(score, 100),

        "reasons": reasons,

        "bos_confirmed": bos_confirmed,

        "choch_confirmed": choch_confirmed
    }