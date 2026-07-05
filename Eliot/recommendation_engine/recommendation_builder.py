# recommendation_engine/recommendation_builder.py

from recommendation_engine.conflict_resolver import (
    resolve_timeframe_conflict,
    get_entry_signal,
    classify_signal_mode,
)


def build_recommendation(
    trend,
    elliott,
    bos,
    choch,
    volume,
    alignment,
    wave_alignment,
    confidence,
    w1_elliott   : dict = None,
    d1_elliott   : dict = None,
    h1_elliott   : dict = None,
    h4_elliott   : dict = None,
    w1_direction : str  = None,
    d1_direction : str  = None,
    h4_direction : str  = None,
    h4_bos       : dict = None,
    h1_bos       : dict = None,

    # المحرك المركزي الجديد (wave_engine/correction_state.py)
    w1_correction : dict = None,
    d1_correction : dict = None,
) -> dict:

    reasons   = []
    score     = 50
    signal    = "WAIT"
    direction = "neutral"

    conf_val = confidence if isinstance(confidence, (int, float)) else 0

    # ── 1. حل التعارض بين timeframes ─────────────────────────────
    conflict_result = None
    entry_signal    = None

    if w1_elliott and d1_elliott and h1_elliott:
        conflict_result = resolve_timeframe_conflict(
            w1_elliott,
            d1_elliott,
            h1_elliott,
            h4_elliott   = h4_elliott,
            w1_direction = w1_direction,
            d1_direction = d1_direction,
            h4_direction = h4_direction,
            h4_bos       = h4_bos,
            h1_bos       = h1_bos,
        )
        entry_signal = get_entry_signal(
            conflict_result,
            h1_elliott,
            confidence=conf_val,
        )
        reasons.append(conflict_result["context"])
        reasons.append(f"D1 دور: {conflict_result['d1_role']}")

        h4_role = conflict_result.get("h4_role", "not_checked")
        if h4_role != "not_checked":
            h4_confirmed = conflict_result.get("h4_confirmed")
            if h4_confirmed:
                reasons.append(f"H4 دور: مؤكِّد ({h4_role})")
            else:
                reasons.append(f"H4 دور: معارض — تم تخفيض الإشارة لانتظار")

        reasons.append(
            f"H1: {h1_elliott.get('pattern')} "
            f"— {h1_elliott.get('current_wave')}"
        )

    # ── فلتر نهاية التصحيح (D1 وW1) ──────────────────────────────
    # المصدر الأساسي الآن: w1_correction/d1_correction (قادمان من
    # wave_engine.correction_state.get_correction_state — مصدر الحقيقة
    # الموحد الوحيد لاكتمال التصحيح في كل النظام). إذا لم يُمرَّرا
    # (مثلاً لأن market_analyzer.py لم يُحدَّث بعد لاستدعاء الدالة
    # المركزية)، نتراجع لفحص صارم محلي بدل قيمة افتراضية غير آمنة.
    d1_ready = False
    w1_ready = False

    if d1_correction:
        d1_ready = d1_correction.get("completed", False)

    if w1_correction:
        w1_ready = w1_correction.get("completed", False)

    # fallback صارم في حال لم يتم تمرير المحرك المركزي لـ D1
    if not d1_correction and d1_elliott:
        d1_ready = (
            d1_elliott.get("phase")
            ==
            "correction_completed"
        )

    # FIX (الباق الجذري المُصلَح هنا): كان هذا الشرط يجعل w1_ready=True
    # تلقائياً بدون أي فحص فعلي لمجرد أن w1_correction لم يُمرَّر —
    # هذا تسبب بظهور w1_correction_completed=True في النتيجة النهائية
    # رغم أن W1 كان فعلياً في wave_A مع phase="correction_ongoing"
    # (تناقض منطقي صريح رصده المستخدم). الآن: نفس معيار fallback
    # الصارم المستخدم لـ D1 — نفحص w1_elliott الفعلي المتوفر دائماً،
    # بدل التراجع المباشر لـ True بلا فحص.
    if not w1_correction and w1_elliott:
        w1_ready = (
            w1_elliott.get("phase")
            ==
            "correction_completed"
        )
    elif not w1_correction and not w1_elliott:
        # لا توجد بيانات W1 إطلاقاً (حالة نادرة جداً) — نسمح بالاستمرار
        # هنا لأن غياب البيانات لا يعني اكتمال التصحيح، لكنه أيضاً لا
        # يجب أن يحجب التداول بشكل صامت بسبب نقص بيانات وليس تحليلاً
        # فعلياً. هذا فرق جوهري عن الحالة السابقة (بيانات موجودة لكن
        # التصحيح لم يكتمل، التي يجب أن تحجب التداول).
        w1_ready = True

    # ── فلتر تأكيد BOS على H4 وH1 ────────────────────────────────
    primary_bias_for_bos = (
        conflict_result.get("primary_bias") if conflict_result else None
    )

    def _bos_matches_bias(bos_dict, bias):
        if bos_dict is None or bias not in ("bullish", "bearish"):
            return False
        bos_type = bos_dict.get("type", "none")
        bos_dir  = bos_dict.get("direction", "none")
        if bos_type == "none" or bos_dir not in ("bullish", "bearish"):
            return False
        return bos_dir == bias

    h4_bos_ready = _bos_matches_bias(h4_bos, primary_bias_for_bos)
    h1_bos_ready = _bos_matches_bias(h1_bos, primary_bias_for_bos)

    structural_confirmed = h4_bos_ready and h1_bos_ready

    # ── 2. الاتجاه الرئيسي ───────────────────────────────────────
    trend_dir = trend.get("direction", "") if trend else ""
    if "bearish" in trend_dir.lower():
        reasons.append("bearish primary trend")
        direction = "sell"
        score    += 10
    elif "bullish" in trend_dir.lower():
        reasons.append("bullish primary trend")
        direction = "buy"
        score    += 10

    # ── 3. Elliott Pattern ────────────────────────────────────────
    elliott_pattern = elliott.get("pattern", "") if elliott else ""
    if "bearish_impulse" in elliott_pattern:
        reasons.append("bearish impulse structure")
        score += 10
    elif "bullish_impulse" in elliott_pattern:
        reasons.append("bullish impulse structure")
        score += 10

    # ── 4. BOS / CHoCH ───────────────────────────────────────────
    from structure_engine.bos_detector import get_bos_summary
    if bos:
        bos_type = bos.get("type", "none") if isinstance(bos, dict) else "none"
        bos_dir  = bos.get("direction", "none") if isinstance(bos, dict) else "none"
        h1_conf  = bos.get("h1_confirmed", False) if isinstance(bos, dict) else False

        if bos_type != "none" and bos_dir != "none":
            reasons.append(get_bos_summary(bos))
            if bos_type == "BOS":
                score += 15
            elif bos_type == "CHoCH":
                score += 10
            if h1_conf:
                score += 5
        else:
            reasons.append("لا يوجد BOS — الإشارة مبنية على Elliott فقط")

    # ── تقرير H4 BOS وH1 BOS ─────────────────────────────────────
    if h4_bos is not None and h4_bos.get("direction") in ("bullish", "bearish"):
        h4_dir  = h4_bos.get("direction", "")
        h4_type = h4_bos.get("type", "")
        if h4_bos_ready:
            reasons.append(f"H4 {h4_type} {h4_dir} — تأكيد هيكلي")
            score += 10
        else:
            reasons.append(f"H4 {h4_type} {h4_dir} — يعارض الاتجاه الأساسي")
            score -= 10
    else:
        reasons.append("H4 BOS غير مؤكد — انتظار كسر هيكلي")

    if h1_bos is not None and h1_bos.get("direction") in ("bullish", "bearish"):
        h1_dir  = h1_bos.get("direction", "")
        h1_type = h1_bos.get("type", "")
        if h1_bos_ready:
            reasons.append(f"H1 {h1_type} {h1_dir} — تأكيد زخمي")
            score += 8
        else:
            reasons.append(f"H1 {h1_type} {h1_dir} — يعارض الاتجاه الأساسي")
            score -= 8
    else:
        reasons.append("H1 BOS غير مؤكد — انتظار كسر زخمي")

    # ── 5. CHoCH ─────────────────────────────────────────────────
    if choch:
        choch_dir = choch.get("direction", "") if isinstance(choch, dict) else str(choch)
        if "bearish" in str(choch_dir).lower():
            reasons.append("bearish CHoCH — انعكاس محتمل")
            score += 5
        elif "bullish" in str(choch_dir).lower():
            reasons.append("bullish CHoCH — انعكاس محتمل")
            score += 5

    # ── 6. Volume ─────────────────────────────────────────────────
    if volume:
        vol_state = volume.get("state", "") if isinstance(volume, dict) else str(volume)
        if "high" in str(vol_state).lower():
            reasons.append("high volume — تأكيد قوي")
            score += 7
        elif "low" in str(vol_state).lower():
            reasons.append("low volume — تأكيد ضعيف")
            score -= 5
        else:
            reasons.append("normal volume")

    # ── 7. Alignment ─────────────────────────────────────────────
    align_score = 0
    if isinstance(alignment, dict):
        align_score = alignment.get("score", 0)
    elif isinstance(alignment, (int, float)):
        align_score = alignment
    reasons.append(f"alignment score {align_score}")
    if align_score >= 70:
        score += 8
    elif align_score < 50:
        score -= 5

    # ── 8. Wave Alignment ────────────────────────────────────────
    wa_score = 0
    if isinstance(wave_alignment, dict):
        wa_score = wave_alignment.get("score", 0)
        aligned  = wave_alignment.get("aligned", False)
        if not aligned:
            reasons.append(f"wave misalignment {wa_score}")
            score -= 5
        else:
            reasons.append(f"wave aligned {wa_score}")
            score += 5
    elif isinstance(wave_alignment, (int, float)):
        wa_score = wave_alignment
        reasons.append(f"wave alignment {wa_score}")

    # ── 9. Confidence ────────────────────────────────────────────
    if conf_val >= 80:
        score += 10
    elif conf_val >= 60:
        score += 5

    # ── 10. تحديد الإشارة النهائية ──────────────────────────────
    signal_mode = "WAIT"
    signal_note = ""

    # ── منع BUY/SELL قبل انتهاء تصحيح D1 ────────────────────────
    if (
        entry_signal in ("BUY_NOW", "STRONG_BUY", "SELL_NOW", "STRONG_SELL")
        and not d1_ready
    ):
        entry_signal = "WAIT_BUY" if "BUY" in entry_signal else "WAIT_SELL"
        reasons.append("التصحيح اليومي (D1) لم يكتمل فعلياً (phase != correction_completed) — تم تخفيض الإشارة إلى WAIT")

    # ── منع التداول عكس تصحيح W1 ──────────────────────────────────
    if (
        entry_signal in ("BUY_NOW", "STRONG_BUY")
        and not w1_ready
    ):
        entry_signal = "WAIT_REVERSAL_CONFIRMATION_BUY"
        reasons.append(
            "التصحيح الأسبوعي W1 ما زال جارياً — لا يسمح بالشراء حتى انتهاء التصحيح"
        )

    # FIX: نقلت هذا الفحص خارج الـ if الخاص بـ w1_ready — كان متداخلاً
    # بداخله سابقاً، فلا يُفحص إطلاقاً إذا كان w1_ready=True (حتى لو
    # كان structural_confirmed=False في تلك الحالة). الآن مستقل ويُطبَّق
    # دائماً على أي BUY_NOW/STRONG_BUY/SELL_NOW/STRONG_SELL متبقٍ.
    if (
        entry_signal in ("BUY_NOW", "STRONG_BUY", "SELL_NOW", "STRONG_SELL")
        and not structural_confirmed
    ):
        if "BUY" in entry_signal:
            entry_signal = "WAIT_REVERSAL_CONFIRMATION_BUY"
        else:
            entry_signal = "WAIT_REVERSAL_CONFIRMATION_SELL"
        reasons.append("BOS على H4/H1 غير مؤكد أو يعارض الاتجاه — انتظار تأكيد هيكلي")

    # ── تحديد الاتجاه والإشارة النهائية ─────────────────────────
    if entry_signal in ("SELL_NOW", "STRONG_SELL"):
        direction = "sell"
        signal_classification = classify_signal_mode(entry_signal, bos)
        signal      = signal_classification["final_signal"]
        signal_mode = signal_classification["mode"]
        signal_note = signal_classification["note"]
        reasons.append(f"[{signal_mode}] {signal_note}")
        if signal_mode == "AGGRESSIVE":
            score -= 10

    elif entry_signal in ("BUY_NOW", "STRONG_BUY"):
        direction = "buy"
        signal_classification = classify_signal_mode(entry_signal, bos)
        signal      = signal_classification["final_signal"]
        signal_mode = signal_classification["mode"]
        signal_note = signal_classification["note"]
        reasons.append(f"[{signal_mode}] {signal_note}")
        if signal_mode == "AGGRESSIVE":
            score -= 10

    elif entry_signal in ("WAIT_SELL", "WAIT_REVERSAL_CONFIRMATION_SELL"):
        signal    = entry_signal
        direction = "sell"
        signal_mode = "WAIT"
        h1_pat  = h1_elliott.get("pattern",      "") if h1_elliott else ""
        h1_wave = h1_elliott.get("current_wave", "") if h1_elliott else ""
        reasons.append(f"{entry_signal} — H1 {h1_pat} {h1_wave} — انتظر تأكيد BOS")

    elif entry_signal in ("WAIT_BUY", "WAIT_REVERSAL_CONFIRMATION_BUY",
                          "WAIT_REVERSAL_CONFIRMATION"):
        signal    = entry_signal
        direction = "buy"
        signal_mode = "WAIT"
        h1_pat  = h1_elliott.get("pattern",      "") if h1_elliott else ""
        h1_wave = h1_elliott.get("current_wave", "") if h1_elliott else ""

        h4_blocked = (
            conflict_result is not None
            and conflict_result.get("h4_confirmed") is False
        )
        d1_undefined = (
            conflict_result is not None
            and conflict_result.get("d1_role") == "undefined"
        )

        if not w1_ready:
            reasons.append(f"{entry_signal} — التصحيح الأسبوعي (W1) لم يكتمل فعلياً بعد")
        elif not d1_ready:
            reasons.append(f"{entry_signal} — التصحيح اليومي (D1) لم يكتمل فعلياً بعد")
        elif entry_signal in ("WAIT_REVERSAL_CONFIRMATION_BUY", "WAIT_REVERSAL_CONFIRMATION"):
            reasons.append(f"{entry_signal} — H1 wave_C اكتملت لكن BOS على H4/H1 لم يتأكد بعد")
        elif h4_blocked:
            reasons.append(f"{entry_signal} — H4 يعارض هيكلياً")
        elif d1_undefined:
            reasons.append(f"{entry_signal} — D1 بدون بيانات كافية")
        else:
            reasons.append(f"{entry_signal} — H1 {h1_pat} {h1_wave} لم تكتمل بعد")

    elif entry_signal == "NO_TRADE":
        signal      = "NO_TRADE"
        direction   = "neutral"
        signal_mode = "WAIT"
        if conflict_result is not None:
            reasons.append(f"NO_TRADE — {conflict_result['context']}")
        else:
            reasons.append("NO_TRADE — بيانات timeframes غير كافية")

    else:
        signal_mode = "WAIT"
        if score >= 70 and direction == "sell":
            signal = "SELL"
        elif score >= 70 and direction == "buy":
            signal = "BUY"
        else:
            signal = "WAIT"

    return {
        "signal"      : signal,
        "signal_mode" : signal_mode,
        "signal_note" : signal_note,
        "direction"   : direction,
        "score"       : max(0, min(score, 100)),
        "confidence"  : conf_val,
        "reasons"     : reasons,
        "context"     : conflict_result["context"]      if conflict_result else "no conflict analysis",
        "primary_bias": conflict_result["primary_bias"] if conflict_result else direction,
        "d1_role"     : conflict_result["d1_role"]      if conflict_result else "unknown",
        "h4_role"     : conflict_result.get("h4_role", "not_checked") if conflict_result else "not_checked",
        "action"      : conflict_result["action"]       if conflict_result else signal,
        "w1_correction_completed": w1_ready,
        "d1_correction_completed": d1_ready,
    }