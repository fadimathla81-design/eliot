# recommendation_engine/conflict_resolver.py

CORRECTION_PATTERNS = {"ABC", "zigzag", "flat", "triangle"}
CORRECTION_WAVES    = {"wave_A", "wave_B", "wave_C"}
MIN_ACTIVE_CONFIDENCE = 30

# ✅ جديد: إذا انهار السعر بأكثر من هذه النسبة من قمة W1
# نعتبر الـ bias الفعلي bearish مؤقتاً بغض النظر عن W1 التاريخي
W1_COLLAPSE_THRESHOLD = 0.15   # 15%


def _bias_of(pattern: str, direction: str | None = None) -> str | None:
    if "bullish_impulse" in pattern or pattern == "bullish_ABC":
        return "bullish"
    if "bearish_impulse" in pattern or pattern == "bearish_ABC":
        return "bearish"
    if direction == "up":
        return "bullish"
    if direction == "down":
        return "bearish"
    return None


def _is_correction(pattern: str) -> bool:
    return pattern in CORRECTION_PATTERNS


def _is_undefined(pattern: str, confidence: int | float | None = None) -> bool:
    if pattern in ("unknown", "", None):
        return True
    if confidence is not None and confidence < MIN_ACTIVE_CONFIDENCE:
        return True
    return False


def _w1_in_correction(w1_pattern: str, w1_current: str, w1_next: str) -> bool:
    return w1_next == "wave_A" or w1_current in CORRECTION_WAVES


def _bos_direction(bos: dict | None) -> str | None:
    """
    يستخرج اتجاه BOS الفعلي بأمان.
    يرجع "bullish" / "bearish" / None (إذا غير متاح أو غير حاسم).
    """
    if not isinstance(bos, dict):
        return None
    direction = str(bos.get("direction", "")).lower()
    if direction in ("bullish", "bearish"):
        return direction
    return None


def _bos_opposes_bias(bos: dict | None, primary_bias: str) -> bool:
    """
    FIX (الإصلاح الجوهري لهذه النسخة):
    يتحقق هل BOS الفعلي (حدث سعري مؤكد: كسر قمة/قاع حقيقي) يعارض
    primary_bias اتجاهياً — لا فقط نمط Elliott (الذي هو تصنيف/تفسير
    تاريخي، وليس دليلاً سعرياً حالياً).

    سابقاً: _check_h4_confirmation كانت تفحص فقط h4_elliott["pattern"]
    وتتجاهل h4_bos/h1_bos الفعليين تماماً، رغم أنهما يُحسبان بشكل
    مستقل في market_analyzer.py ويُمرَّران لـ build_recommendation —
    لكنهما لا يصلان أبداً لمنطق القرار الحقيقي. هذا تسبب بظهور
    BUY_NOW بثقة 98% بينما H4 BOS كان bearish فعلياً.

    الآن: BOS معارض = حاجز صارم (AND condition)، اتساقاً مع المنطق
    المطبَّق في signal_engine._evaluate_h1_elliott (h4_bullish_bos
    and h1_bullish_bos كشرط AND لا نسبي).
    """
    bos_dir = _bos_direction(bos)
    if bos_dir is None:
        return False  # لا بيانات حاسمة → لا نمنع بسبب الغياب
    return bos_dir != primary_bias


def _detect_active_collapse(
    w1_elliott  : dict,
    w1_pivots   : dict | None,
    current_price: float | None,
    d1_elliott  : dict | None = None,
    h4_direction: str | None = None,
    h1_direction: str | None = None,
) -> bool:
    """
    ✅ يكتشف إذا كان السوق في انهيار فعلي نشط بغض النظر عن W1 التاريخي.

    الشروط (كلها يجب أن تتحقق):
    1. W1 في موجة تصحيحية (A/B/C)
    2. السعر انهار أكثر من W1_COLLAPSE_THRESHOLD من آخر قمة W1
    3. D1 في wave_C هابطة (تأكيد أن التصحيح عميق)
    4. H4 وH1 اتجاههما down (تأكيد الزخم الهابط)
    """
    w1_current = w1_elliott.get("current_wave", "")
    if w1_current not in CORRECTION_WAVES:
        return False

    if w1_pivots and current_price is not None:
        highs = w1_pivots.get("highs", [])
        if highs:
            last_high = highs[-1]["price"]
            if last_high > 0:
                drop_pct = (last_high - current_price) / last_high
                if drop_pct < W1_COLLAPSE_THRESHOLD:
                    return False
            else:
                return False
        else:
            return False
    else:
        return False

    if d1_elliott is not None:
        d1_wave = d1_elliott.get("current_wave", "")
        d1_dir  = d1_elliott.get("direction", "")
        if d1_wave != "wave_C" or d1_dir != "down":
            return False
    else:
        return False

    if h4_direction != "down" or h1_direction != "down":
        return False

    return True


def _check_h4_confirmation(
    primary_bias: str,
    h4_elliott  : dict,
    h4_direction: str | None = None,
    h4_bos      : dict | None = None,
) -> dict:
    """
    FIX: تضيف الآن فحص h4_bos الفعلي بالإضافة لفحص نمط Elliott.

    قاعدة جديدة صارمة: إذا h4_bos يعارض primary_bias اتجاهياً،
    التأكيد يُرفض فوراً (confirmed=False) — بغض النظر عن نمط H4
    Elliott، لأن BOS هو دليل سعري حالي فعلي، لا تصنيف تاريخي.
    """
    # ── الحاجز الصارم: BOS فعلي معارض يمنع التأكيد مباشرة ──────
    if _bos_opposes_bias(h4_bos, primary_bias):
        bos_dir = _bos_direction(h4_bos)
        return {
            "confirmed": False,
            "strength" : "none",
            "reason"   : (
                f"H4 BOS فعلي ({bos_dir}) يعارض {primary_bias} — "
                f"حاجز صارم، لا يُسمح بالتجاوز بغض النظر عن نمط Elliott"
            ),
        }

    h4_pattern = h4_elliott.get("pattern", "")

    expected_impulse = (
        "bullish_impulse" if primary_bias == "bullish" else "bearish_impulse"
    )
    opposite_impulse = (
        "bearish_impulse" if primary_bias == "bullish" else "bullish_impulse"
    )

    if h4_pattern == expected_impulse:
        return {
            "confirmed": True,
            "strength" : "full",
            "reason"   : f"H4 {h4_pattern} يؤكد {primary_bias} بقوة كاملة",
        }

    if h4_pattern == opposite_impulse:
        return {
            "confirmed": False,
            "strength" : "none",
            "reason"   : f"H4 {h4_pattern} يعارض {primary_bias} هيكلياً",
        }

    if _is_correction(h4_pattern):
        h4_bias = _bias_of(h4_pattern, h4_direction)

    # H4 التصحيحي يسير بعكس الاتجاه الرئيسي
    # => لا نسمح بالدخول حالياً
        if h4_bias is not None and h4_bias != primary_bias:
            return {
                "confirmed": False,
                "strength" : "none",
                "reason"   : (
                    f"H4 في تصحيح {h4_pattern} واتجاهه الفعلي "
                    f"({h4_bias}) يعارض {primary_bias}"
                ),
            }

    # H4 التصحيحي يسير مع الاتجاه الرئيسي
        if h4_bias is not None and h4_bias == primary_bias:
            return {
                "confirmed": True,
                "strength" : "full",
                "reason"   : (
                    f"H4 ({h4_pattern}) اتجاهه الفعلي "
                    f"يؤكد {primary_bias}"
                ),
            }

    # لا يوجد اتجاه واضح
        return {
            "confirmed": True,
            "strength" : "partial",
            "reason"   : (
                f"H4 في تصحيح {h4_pattern} لكن اتجاهه غير واضح"
            ),
        }

    return {
        "confirmed": True,
        "strength" : "partial",
        "reason"   : f"H4 ({h4_pattern}) غير حاسم — يُسمح بالاستمرار بثقة جزئية",
    }


def resolve_timeframe_conflict(
    w1_elliott   : dict,
    d1_elliott   : dict,
    h1_elliott   : dict,
    h4_elliott   : dict | None = None,
    w1_direction : str | None = None,
    d1_direction : str | None = None,
    h4_direction : str | None = None,
    # ✅ جديد: للكشف عن الانهيار الفعلي
    w1_pivots    : dict | None = None,
    current_price: float | None = None,
    h1_direction : str | None = None,
    # ✅ جديد (هذا الإصلاح): BOS فعلي مستقل لكل من H4 وH1
    h4_bos       : dict | None = None,
    h1_bos       : dict | None = None,
) -> dict:

    w1_pattern    = w1_elliott.get("pattern", "")
    d1_pattern    = d1_elliott.get("pattern", "")
    d1_confidence = d1_elliott.get("confidence", 0)
    w1_current    = w1_elliott.get("current_wave", "")
    w1_next       = w1_elliott.get("next_wave", "")
    d1_next       = d1_elliott.get("next_wave", "")

    w1_bias = _bias_of(w1_pattern, w1_direction)
    d1_bias = _bias_of(d1_pattern, d1_direction)

    d1_is_undefined  = _is_undefined(d1_pattern, d1_confidence)
    w1_in_correction = _w1_in_correction(w1_pattern, w1_current, w1_next)

    if _is_correction(d1_pattern):
        d1_completed = d1_next in ("trend_resumption", "impulse")
    else:
        d1_completed = d1_next == "wave_A"

    # ══════════════════════════════════════════════════════════════
    # ✅ كشف الانهيار الفعلي النشط
    # ══════════════════════════════════════════════════════════════
    active_collapse = _detect_active_collapse(
        w1_elliott   = w1_elliott,
        w1_pivots    = w1_pivots,
        current_price= current_price,
        d1_elliott   = d1_elliott,
        h4_direction = h4_direction,
        h1_direction = h1_direction,
    )

    if active_collapse and w1_bias == "bullish":
        w1_bias = "bearish"
        collapse_note = (
            f"⚠️ انهيار نشط: W1 تاريخياً bullish لكن السعر انهار "
            f">{int(W1_COLLAPSE_THRESHOLD*100)}% من القمة — "
            f"bias معدّل إلى bearish مؤقتاً"
        )
    else:
        collapse_note = None

    base_result = None

    # ══════════════════════════════════════════════════════════════
    # CASE UNDEFINED: W1 واضح لكن D1 غير محدد
    # ══════════════════════════════════════════════════════════════
    if (
        base_result is None
        and w1_bias is not None
        and w1_in_correction
        and d1_is_undefined
    ):
        primary_bias = w1_bias
        action_verb  = "BUY" if primary_bias == "bullish" else "SELL"
        base_result = {
            "conflict"    : False,
            "context"     : (
                f"W1={w1_pattern} واضح ({primary_bias}) لكن D1 بدون بيانات كافية "
                f"— انتظر تأكيد D1"
            ),
            "primary_bias": primary_bias,
            "d1_role"     : "undefined",
            "d1_completed": False,
            "action"      : f"انتظر تأكيد D1 قبل {action_verb}",
            "entry_timing": "D1_confirmation",
        }

    # ══════════════════════════════════════════════════════════════
    # CASE COLLAPSE — انهيار نشط مؤكد
    # ══════════════════════════════════════════════════════════════
    if (
        base_result is None
        and active_collapse
        and _is_correction(d1_pattern)
    ):
        d1_wave = d1_elliott.get("current_wave", "")
        d1_phase = d1_elliott.get("phase", "")

        if d1_wave == "wave_C" and d1_phase in ("correction_completed",):
            base_result = {
                "conflict"    : False,
                "context"     : (
                    f"انهيار نشط — D1 wave_C اكتملت — انتظر BOS صاعد على H4+H1"
                ),
                "primary_bias": "bearish",
                "d1_role"     : "collapse_wave_C_completed",
                "d1_completed": True,
                "action"      : "WAIT_REVERSAL_CONFIRMATION — انتظر BOS صاعد",
                "entry_timing": "H4_H1_BOS",
            }
        else:
            base_result = {
                "conflict"    : False,
                "context"     : (
                    f"انهيار نشط — D1 لا تزال في {d1_wave} — "
                    f"انتظر اكتمال wave_C قبل البحث عن انعكاس"
                ),
                "primary_bias": "bearish",
                "d1_role"     : "collapse_in_progress",
                "d1_completed": False,
                "action"      : "NO_TRADE — السوق في انهيار نشط، انتظر اكتمال D1 wave_C",
                "entry_timing": None,
            }

    # ══════════════════════════════════════════════════════════════
    # CASE NEW: W1 في تصحيح + D1 تصحيح
    # ══════════════════════════════════════════════════════════════
    if base_result is None and w1_in_correction and _is_correction(d1_pattern):
        primary_bias = w1_bias
        action_verb  = "BUY" if primary_bias == "bullish" else (
            "SELL" if primary_bias == "bearish" else None
        )
        if primary_bias is not None:
            if d1_completed:
                base_result = {
                    "conflict"    : False,
                    "context"     : (
                        f"D1={d1_pattern} هو تصحيح W1 المتوقع وقد اكتمل "
                        f"— استمرار {primary_bias}"
                    ),
                    "primary_bias": primary_bias,
                    "d1_role"     : "corrective_wave_A_completed",
                    "d1_completed": True,
                    "action"      : f"{action_verb} عند تأكيد H1",
                    "entry_timing": "H1",
                }
            else:
                base_result = {
                    "conflict"    : False,
                    "context"     : (
                        f"D1={d1_pattern} هو تصحيح W1 المتوقع — لا يزال جارياً"
                    ),
                    "primary_bias": primary_bias,
                    "d1_role"     : "corrective_wave_A_in_progress",
                    "d1_completed": False,
                    "action"      : f"انتظر اكتمال D1 قبل {action_verb}",
                    "entry_timing": "H1",
                }

    # ══════════════════════════════════════════════════════════════
    # CASE A/B: W1 في تصحيح + D1 بعكس اتجاه W1
    # ══════════════════════════════════════════════════════════════
    if (
        base_result is None
        and w1_bias is not None
        and w1_in_correction
        and d1_bias is not None
        and d1_bias != w1_bias
    ):
        action_verb = "SELL" if w1_bias == "bearish" else "BUY"
        if d1_completed:
            base_result = {
                "conflict"    : False,
                "context"     : f"تصحيح W1 اكتمل ({d1_pattern}) — استمرار {w1_bias} متوقع",
                "primary_bias": w1_bias,
                "d1_role"     : "corrective_wave_A_completed",
                "d1_completed": True,
                "action"      : f"{action_verb} عند تأكيد H1",
                "entry_timing": "H1",
            }
        else:
            base_result = {
                "conflict"    : False,
                "context"     : f"تصحيح W1 ({d1_pattern}) لا يزال جارياً",
                "primary_bias": w1_bias,
                "d1_role"     : "corrective_wave_A_in_progress",
                "d1_completed": False,
                "action"      : f"انتظر اكتمال D1 قبل {action_verb}",
                "entry_timing": "H1",
            }

    # ══════════════════════════════════════════════════════════════
    # CASE C: توافق كامل W1+D1
    # ══════════════════════════════════════════════════════════════
    if (
        base_result is None
        and w1_bias is not None
        and d1_bias is not None
        and w1_bias == d1_bias
    ):
        action_verb = "SELL" if w1_bias == "bearish" else "BUY"
        label = "هبوطي" if w1_bias == "bearish" else "صعودي"
        base_result = {
            "conflict"    : False,
            "context"     : f"توافق {label} كامل W1+D1 (W1={w1_pattern}, D1={d1_pattern})",
            "primary_bias": w1_bias,
            "d1_role"     : "aligned",
            "d1_completed": d1_completed,
            "action"      : f"{action_verb} عند تأكيد H1",
            "entry_timing": "H1",
        }

    # ══════════════════════════════════════════════════════════════
    # CASE D: تعارض مؤقت
    # ══════════════════════════════════════════════════════════════
    if (
        base_result is None
        and w1_bias is not None
        and d1_bias is not None
        and d1_bias != w1_bias
        and not w1_in_correction
        and not _is_correction(d1_pattern)
    ):
        base_result = {
            "conflict"    : True,
            "context"     : f"W1 لا يزال في impulse و D1 عكسه — تعارض مؤقت",
            "primary_bias": w1_bias,
            "d1_role"     : "conflicting",
            "d1_completed": False,
            "action"      : "انتظر وضوح W1 قبل الدخول",
            "entry_timing": None,
        }

    # ══════════════════════════════════════════════════════════════
    # الحالة الافتراضية
    # ══════════════════════════════════════════════════════════════
    if base_result is None:
        base_result = {
            "conflict"    : True,
            "context"     : f"تعارض حقيقي: W1={w1_pattern} vs D1={d1_pattern}",
            "primary_bias": "neutral",
            "d1_role"     : "conflicting",
            "d1_completed": False,
            "action"      : "NO_TRADE — انتظر وضوح الاتجاه",
            "entry_timing": None,
        }

    if collapse_note:
        base_result["context"] = collapse_note + " | " + base_result["context"]

    base_result["h4_role"]      = "not_checked"
    base_result["h4_confirmed"] = None
    # ✅ جديد: نخزّن نتيجة فحص h1_bos أيضاً، يُستخدم في get_entry_signal
    base_result["h1_bos_blocked"] = False
    base_result["h1_bos_reason"]  = None

    if (
        h4_elliott is not None
        and not base_result["conflict"]
        and base_result["primary_bias"] in ("bullish", "bearish")
    ):
        primary_bias = base_result["primary_bias"]

        # FIX: تمرير h4_bos الفعلي لفحص الحاجز الصارم
        h4_check = _check_h4_confirmation(
            primary_bias, h4_elliott, h4_direction, h4_bos=h4_bos
        )
        base_result["h4_role"]      = h4_check["strength"]
        base_result["h4_confirmed"] = h4_check["confirmed"]

        if not h4_check["confirmed"]:
            action_verb  = "SELL" if primary_bias == "bearish" else "BUY"
            base_result["context"] += f" | H4 يعارض: {h4_check['reason']}"
            base_result["action"]   = f"انتظر — H4 يعارض {action_verb} حالياً"
            base_result["entry_timing"] = None
        else:
            base_result["context"] += f" | H4: {h4_check['reason']}"

        # ✅ جديد: فحص حاجز H1 BOS بشكل مستقل (نفس مبدأ H4)
        if _bos_opposes_bias(h1_bos, primary_bias):
            h1_bos_dir = _bos_direction(h1_bos)
            base_result["h1_bos_blocked"] = True
            base_result["h1_bos_reason"]  = (
                f"H1 BOS فعلي ({h1_bos_dir}) يعارض {primary_bias} — حاجز صارم"
            )
            base_result["context"] += f" | {base_result['h1_bos_reason']}"

    return base_result


def get_entry_signal(
    conflict_result: dict,
    h1_elliott     : dict,
    h4_elliott     : dict | None = None,
    confidence     : float | None = None,
) -> str:

    if conflict_result["conflict"]:
        return "NO_TRADE"

    primary_bias  = conflict_result["primary_bias"]
    d1_role       = conflict_result.get("d1_role", "")
    d1_completed  = conflict_result.get("d1_completed", False)
    entry_timing  = conflict_result.get("entry_timing")

    h4_confirmed = conflict_result.get("h4_confirmed", None)
    h4_blocked   = h4_confirmed is False
    
    # ✅ جديد: حاجز H1 BOS الصارم (مستقل عن h4_blocked)
    h1_bos_blocked = conflict_result.get("h1_bos_blocked", False)
    
    # H4 must finish correction before allowing BUY
    if (
        primary_bias == "bullish"
        and h4_elliott is not None
        and h4_elliott.get("pattern") in ("ABC", "zigzag", "flat", "triangle")
        and h4_elliott.get("phase") != "correction_completed"
    ):
        h4_blocked = True
        

    # ✅ جديد: حاجز H1 BOS الصارم (مستقل عن h4_blocked)
    h1_bos_blocked = conflict_result.get("h1_bos_blocked", False)

    h1_pattern = h1_elliott.get("pattern", "")
    h1_wave    = h1_elliott.get("current_wave", "")
    h1_next    = h1_elliott.get("next_wave", "")

    is_strong = confidence is not None and confidence >= 75

    print(f"\nENTRY SIGNAL DEBUG")
    print(f"primary_bias={primary_bias} | d1_role={d1_role} | d1_completed={d1_completed}")
    print(f"h4_confirmed={h4_confirmed} | h4_blocked={h4_blocked} | h1_bos_blocked={h1_bos_blocked}")
    print(f"h1_pattern={h1_pattern} | h1_wave={h1_wave} | h1_next={h1_next}")
    print(f"confidence={confidence} | is_strong={is_strong}")

    # ── انهيار نشط: انتظر تأكيد انعكاس فقط ──────────────────────
    if d1_role == "collapse_wave_C_completed":
        return "WAIT_REVERSAL_CONFIRMATION_BUY"

    if d1_role == "collapse_in_progress":
        return "NO_TRADE"

    # ── BEARISH ──────────────────────────────────────────────────
    if primary_bias == "bearish":
        if h4_blocked or h1_bos_blocked:
            return "WAIT_SELL"
        if not d1_completed and d1_role in ("corrective_wave_A_in_progress", "undefined"):
            return "WAIT_SELL"
        if d1_completed or d1_role == "aligned":
            now_signal = "STRONG_SELL" if is_strong else "SELL_NOW"
            if h1_pattern == "ABC" and h1_wave == "wave_C" and h1_next in ("trend_resumption", "impulse"):
                return now_signal
            if "bearish_impulse" in h1_pattern:
                return now_signal
            if h1_pattern == "ABC" and h1_wave != "wave_C":
                return "WAIT_SELL"
            if "bullish" in h1_pattern:
                return "WAIT_SELL"
        return "WAIT_SELL"

    # ── BULLISH ──────────────────────────────────────────────────
    if primary_bias == "bullish":
        if h4_blocked or h1_bos_blocked:
            return "WAIT_BUY"
        if not d1_completed and d1_role in ("corrective_wave_A_in_progress", "undefined"):
            return "WAIT_BUY"
        if d1_completed or d1_role == "aligned":
            now_signal = "STRONG_BUY" if is_strong else "BUY_NOW"
            if h1_pattern == "ABC" and h1_wave == "wave_C" and h1_next in ("trend_resumption", "impulse"):
                return now_signal
            if "bullish_impulse" in h1_pattern:
                return now_signal
            if h1_pattern == "ABC" and h1_wave != "wave_C":
                return "WAIT_BUY"
            if "bearish" in h1_pattern:
                return "WAIT_BUY"
        return "WAIT_BUY"

    return "WAIT"


def classify_signal_mode(entry_signal: str, bos: dict) -> dict:
    bos_direction = ""
    if isinstance(bos, dict):
        bos_direction = str(bos.get("direction", "")).lower()

    has_bos = bos_direction in ("bullish", "bearish")

    immediate_sell = ("SELL_NOW", "STRONG_SELL")
    immediate_buy  = ("BUY_NOW", "STRONG_BUY")

    if entry_signal in immediate_sell + immediate_buy:
        expected_bos_dir = "bearish" if entry_signal in immediate_sell else "bullish"
        if has_bos and bos_direction == expected_bos_dir:
            return {
                "mode"        : "CONFIRMED",
                "final_signal": entry_signal,
                "note"        : "Elliott + BOS متوافقان — دخول مؤكد",
            }
        return {
            "mode"        : "AGGRESSIVE",
            "final_signal": f"{entry_signal}_EARLY",
            "note"        : "إشارة استباقية — بدون تأكيد BOS",
        }

    return {
        "mode"        : "WAIT",
        "final_signal": entry_signal,
        "note"        : "لا تغيير",
    }