# recommendation_engine/trade_setup_builder.py


# ── إعدادات الـ ATR Buffer ────────────────────────
ATR_MULTIPLIER       = 1.5     # عدد مرات ATR المستخدمة كهامش أمان (invalidation)
EXECUTION_ATR_RATIO  = 0.5     # نسبة ATR المستخدمة لعرض منطقة التنفيذ الفعلية
FALLBACK_PERCENTAGE  = 0.003   # 0.3% — يُستخدم فقط إذا ATR غير متاح

# إشارات الدخول الفوري
IMMEDIATE_SIGNALS = (
    "SELL_NOW", "BUY_NOW",
    "SELL_NOW_EARLY", "BUY_NOW_EARLY",
    "STRONG_SELL", "STRONG_BUY",
    "STRONG_SELL_EARLY", "STRONG_BUY_EARLY",
)


def _get_fib_level(fib: dict, level: str, fallback: float | None = None) -> float | None:
    """
    يقرأ مستوى فيبوناتشي من fib["retracement"] بأمان.

    CHANGE (تضييق entry_zone): نحتاج مستوى "50" الذي قد لا يكون
    موجوداً في كل تطبيقات fibonacci_engine. لو غير موجود، نستخدم
    fallback (يُمرَّر من المُستدعي، عادة المتوسط بين 38.2 و61.8 —
    وهو تقريب رياضي مقبول لمستوى 50% لأن 38.2 و61.8 متماثلان حول 50).
    """
    retracement = fib.get("retracement", {}) if fib else {}
    value = retracement.get(level)
    if value is not None:
        return value
    return fallback


def _last_price(pivot_list: list) -> float | None:
    if pivot_list:
        return pivot_list[-1]["price"]
    return None


def _calc_invalidation_sell(current_price, h1_highs, w1_highs, atr_h1):
    """
    FIX: نبحث عن آخر high على H1 يكون فوق السعر الحالي فعلاً،
    بدل أخذ آخر عنصر في القائمة بغض النظر عن موقعه من السعر.
    هذا يمنع حالة SL أسفل السعر في صفقة SELL.
    """
    source = "H1"

    last_high = None
    if h1_highs and current_price is not None:
        # أحدث high فوق السعر الحالي
        candidates = [s for s in h1_highs if s["price"] > current_price]
        if candidates:
            last_high = candidates[-1]["price"]
    elif h1_highs:
        last_high = _last_price(h1_highs)

    # إذا لم نجد على H1 → انتقل لـ W1
    if last_high is None:
        fallback = None
        if w1_highs and current_price is not None:
            candidates = [s for s in w1_highs if s["price"] > current_price]
            if candidates:
                fallback = candidates[-1]["price"]
        if fallback is None:
            fallback = _last_price(w1_highs)
        if fallback is not None:
            last_high = fallback
            source    = "W1"

    if last_high is None:
        return None, "لا توجد بيانات pivots كافية"

    if atr_h1 is not None and atr_h1 > 0:
        buffer = atr_h1 * ATR_MULTIPLIER
        value  = round(last_high + buffer, 5)
        method = (
            f"{source} last_high + {ATR_MULTIPLIER}xATR "
            f"(ref={last_high}, ATR={atr_h1}, buffer={round(buffer,5)})"
        )
        return value, method

    value  = round(last_high * (1 + FALLBACK_PERCENTAGE), 5)
    method = f"{source} last_high x {1+FALLBACK_PERCENTAGE} (ref={last_high}, fallback)"
    return value, method


def _calc_invalidation_buy(current_price, h1_lows, w1_lows, atr_h1):
    """
    FIX: نبحث عن آخر low على H1 يكون أسفل السعر الحالي فعلاً،
    بدل أخذ آخر عنصر في القائمة بغض النظر عن موقعه من السعر.
    هذا يمنع حالة SL فوق السعر في صفقة BUY.
    """
    source = "H1"

    last_low = None
    if h1_lows and current_price is not None:
        # أحدث low أسفل السعر الحالي
        candidates = [s for s in h1_lows if s["price"] < current_price]
        if candidates:
            last_low = candidates[-1]["price"]
    elif h1_lows:
        last_low = _last_price(h1_lows)

    # إذا لم نجد على H1 → انتقل لـ W1
    if last_low is None:
        fallback = None
        if w1_lows and current_price is not None:
            candidates = [s for s in w1_lows if s["price"] < current_price]
            if candidates:
                fallback = candidates[-1]["price"]
        if fallback is None:
            fallback = _last_price(w1_lows)
        if fallback is not None:
            last_low = fallback
            source   = "W1"

    if last_low is None:
        return None, "لا توجد بيانات pivots كافية"

    if atr_h1 is not None and atr_h1 > 0:
        buffer = atr_h1 * ATR_MULTIPLIER
        value  = round(last_low - buffer, 5)
        method = (
            f"{source} last_low - {ATR_MULTIPLIER}xATR "
            f"(ref={last_low}, ATR={atr_h1}, buffer={round(buffer,5)})"
        )
        return value, method

    value  = round(last_low * (1 - FALLBACK_PERCENTAGE), 5)
    method = f"{source} last_low x {1-FALLBACK_PERCENTAGE} (ref={last_low}, fallback)"
    return value, method


def _calc_structural_stop_sell(current_price, d1_highs, w1_highs, atr_h1):
    """
    FIX (هذا الإصلاح): سابقاً كانت تأخذ ببساطة "آخر D1 high" بدون أي
    تحقق من موقعه الفعلي بالنسبة لـ current_price — هذا تسبب بظهور
    structural_stop أقرب من trade_stop أحياناً (ترتيب معكوس: الستوب
    "الهيكلي" المفترض أبعد كان يظهر أقرب من الستوب "التكتيكي").

    الآن: نفس منطق _calc_invalidation_sell بالضبط (بحث عن أحدث pivot
    فعلياً فوق current_price)، لكن من D1 (لا H1)، وبدون هامش ATR إضافي
    خاص بها — الفارق الطبيعي بين D1 وH1 كافٍ عادة لجعلها أبعد. التحقق
    النهائي من الترتيب الصحيح (أبعد من trade_stop) يحدث صراحة في
    build_trade_setup بعد حساب كلا القيمتين، كحماية مضاعفة.
    """
    source = "D1"

    last_high = None
    if d1_highs and current_price is not None:
        candidates = [s for s in d1_highs if s["price"] > current_price]
        if candidates:
            last_high = candidates[-1]["price"]
    elif d1_highs:
        last_high = _last_price(d1_highs)

    if last_high is None:
        fallback = None
        if w1_highs and current_price is not None:
            candidates = [s for s in w1_highs if s["price"] > current_price]
            if candidates:
                fallback = candidates[-1]["price"]
        if fallback is None:
            fallback = _last_price(w1_highs)
        if fallback is not None:
            last_high = fallback
            source    = "W1"

    return last_high, source


def _calc_structural_stop_buy(current_price, d1_lows, w1_lows, atr_h1,
                              tactical_stop=None):
    """
    FIX (هذا الإصلاح): سابقاً كانت تأخذ ببساطة "آخر D1 low" بدون أي
    تحقق من موقعه الفعلي بالنسبة لـ current_price — نفس الباق بالضبط
    الذي أصلحناه سابقاً في trade_stop، لكنه لم يُصلَح هنا وقتها (وُثّق
    نظرياً فقط، دون تطبيق فعلي). هذا تسبب بظهور structural_stop
    (3959.06) أقرب من trade_stop (3909.53) في تشغيل فعلي — ترتيب
    معكوس، لأن آخر D1 low المسجَّل كان قد كُسر نزولاً فعلياً، فالكود
    استمر يستخدمه كأنه لا يزال "الحد الأدنى" الحالي.

    FIX 2 (هذه النسخة): إضافة شرط tactical_stop — البحث عن D1 low
    يكون فعلياً **أبعد** (أدنى) من trade_stop، لا فقط أسفل current_price.
    هذا يمنع حالة تساوي structural_stop مع trade_stop (كانت تظهر عندما
    الحماية الصريحة في build_trade_setup تُعدَّل structural ليساوي tactical
    لأن D1 low الأقرب كان أعلى من H1 low المستخدم لـtrade_stop).
    إذا لم يتوفر D1 low أبعد → نتراجع لـ W1 مباشرة (دائماً أبعد بطبيعته).
    """
    source = "D1"

    last_low = None
    if d1_lows and current_price is not None:
        # FIX 2: نبحث عن D1 low أسفل current_price وأبعد من tactical_stop
        candidates = [s for s in d1_lows if s["price"] < current_price]
        if tactical_stop is not None:
            # أبعد = أدنى من tactical_stop لصفقة BUY
            candidates = [s for s in candidates if s["price"] < tactical_stop]
        if candidates:
            # نأخذ الأحدث (index الأكبر) من الخيارات المتاحة
            last_low = max(candidates, key=lambda s: s["index"])["price"]
    elif d1_lows:
        last_low = _last_price(d1_lows)

    # إذا لم نجد D1 low مناسب → W1 مباشرة (دائماً أبعد بطبيعته)
    if last_low is None:
        fallback = None
        if w1_lows and current_price is not None:
            candidates = [s for s in w1_lows if s["price"] < current_price]
            if tactical_stop is not None:
                candidates = [s for s in candidates if s["price"] < tactical_stop]
            if candidates:
                fallback = max(candidates, key=lambda s: s["index"])["price"]
        if fallback is None:
            fallback = _last_price(w1_lows)
        if fallback is not None:
            last_low = fallback
            source   = "W1"

    return last_low, source


def _calc_catastrophic_stop_sell(w1_highs):
    """
    wave_4 high = ثاني آخر قمة على W1
    كسرها يلغي العدّ الموجي الهابط كله.
    """
    if len(w1_highs) < 2:
        return None
    return w1_highs[-2]["price"]


def _calc_catastrophic_stop_buy(w1_lows):
    """
    wave_4 low = ثاني آخر قاع على W1
    كسره يلغي العدّ الموجي الصاعد كله.
    """
    if len(w1_lows) < 2:
        return None
    return w1_lows[-2]["price"]


def _build_targets_sell(reference_price, h1_lows, w1_lows, fib_swing_low):
    """
    FIX (targets): تستقبل reference_price (حد منطقة الدخول، لا current_price).
    سابقاً كانت تفلتر الأهداف بالمقارنة مع current_price مباشرة، فإذا كان
    السعر الحالي بعيداً عن entry_zone، يمكن أن يمر هدف أعلى من current_price
    لكنه لا يزال أعلى من (أي "خلف") نقطة الدخول الفعلية المتوقعة لصفقة sell
    (الأهداف يجب أن تكون أقل من سعر الدخول الفعلي، لا من السعر الحالي وحده).
    المستدعي يُفترض أن يمرر execution_zone[0] (حد الزون السفلي) كمرجع.
    """
    candidates = []
    h1_low = _last_price(h1_lows)
    if h1_low is not None:
        candidates.append(h1_low)
    w1_low = _last_price(w1_lows)
    if w1_low is not None:
        candidates.append(w1_low)
    if fib_swing_low is not None:
        candidates.append(fib_swing_low)
    if reference_price is not None:
        candidates = [c for c in candidates if c < reference_price]
    return sorted(set(candidates), reverse=True)


def _calc_intermediate_targets_buy(entry_zone_high, swing_high, swing_low):
    """
    NEW: يحسب أهدافاً وسيطة واقعية بناءً على طول الموجة التصحيحية الحالية،
    لا على الامتداد التاريخي الكامل (الذي كان يُنتج أهدافاً بعيدة جداً
    كـ 5596 و6229 بينما السعر عند 4020 فعلياً).

    المنطق: الموجة الصاعدة المتوقعة (wave_B أو استئناف الاتجاه) عادة
    ترتد بنسب 38.2%-61.8%-100% من الموجة التصحيحية السابقة (المسافة بين
    swing_high وأسفل منطقة الدخول)، وهذا ينتج أهدافاً قريبة ومنطقية.

    Args:
        entry_zone_high: أعلى حد في منطقة الدخول (نقطة الانطلاق المتوقعة)
        swing_high: أعلى نقطة W1 (الهدف النهائي البعيد — يُبقى كـ TP النهائي)
        swing_low: أدنى نقطة W1 (قاع التصحيح المرجعي)

    Returns:
        قائمة بأهداف وسيطة مرتبة تصاعدياً
    """
    if entry_zone_high is None or swing_high is None or swing_low is None:
        return []

    # طول الموجة التصحيحية: من الأعلى التاريخي لأسفل منطقة الدخول
    correction_length = swing_high - entry_zone_high
    if correction_length <= 0:
        return []

    targets = []
    # TP1: ارتداد 38.2% من الموجة التصحيحية (هدف محافظ، قريب)
    tp1 = round(entry_zone_high + correction_length * 0.382, 2)
    # TP2: ارتداد 61.8% من الموجة التصحيحية (هدف متوسط)
    tp2 = round(entry_zone_high + correction_length * 0.618, 2)
    # TP3: ارتداد 100% من الموجة التصحيحية = العودة للقمة الأصلية
    tp3 = round(swing_high, 2)

    for t in [tp1, tp2, tp3]:
        if t > entry_zone_high:
            targets.append(t)

    return sorted(set(targets))


def _build_targets_buy(reference_price, h1_highs, w1_highs, fib_extension_127,
                       fib=None, entry_zone_high=None):
    """
    FIX (targets): تستقبل reference_price (حد منطقة الدخول، لا current_price).
    سابقاً كانت تفلتر الأهداف بالمقارنة مع current_price مباشرة، فسمحت بمرور
    أهداف أقل من entry_zone بالكامل طالما كانت أعلى من current_price فقط
    (هذا تحديداً ما تسبب بظهور هدف 4096.97 رغم أنه كان أقل من entry_zone
    [4145.22, 4444.65] بالكامل — هدف خلف نقطة الدخول، غير منطقي لصفقة buy).
    المستدعي يُفترض أن يمرر execution_zone[1] (حد الزون العلوي) كمرجع.

    NEW: إضافة أهداف وسيطة واقعية من الموجة الحالية (38.2%, 61.8%, 100%
    من طول الموجة التصحيحية) بدل الاعتماد فقط على الامتداد التاريخي الكامل
    (الذي كان يُنتج أهداف 5596 و6229 بينما السعر عند 4020 — بعيدة جداً).
    """
    candidates = []

    # 1. أهداف وسيطة واقعية من الموجة الحالية (الأولوية الأولى)
    if fib is not None and entry_zone_high is not None:
        swing_high = fib.get("swing_high")
        swing_low  = fib.get("swing_low")
        intermediate = _calc_intermediate_targets_buy(entry_zone_high, swing_high, swing_low)
        candidates.extend(intermediate)

    # 2. آخر H1 high (لا يزال مفيداً كمقاومة قريبة قد تكون هدفاً)
    h1_high = _last_price(h1_highs)
    if h1_high is not None:
        candidates.append(h1_high)

    # 3. آخر W1 high (هدف بعيد، يبقى كـ TP النهائي)
    w1_high = _last_price(w1_highs)
    if w1_high is not None:
        candidates.append(w1_high)

    # 4. امتداد فيبوناتشي 127.2% من W1 (أبعد هدف ممكن)
    if fib_extension_127 is not None:
        candidates.append(fib_extension_127)

    # فلتر: فقط أهداف فوق reference_price (حد الزون العلوي)
    if reference_price is not None:
        candidates = [c for c in candidates if c > reference_price]

    return sorted(set(candidates))


def format_distance(price_diff, pip_multiplier, reference_price=None):
    price_diff = abs(price_diff)
    if pip_multiplier >= 10000:
        return f"{round(price_diff * pip_multiplier, 1)} pip"
    if pip_multiplier <= 100:
        if reference_price is not None and reference_price >= 1000:
            return f"${round(price_diff, 2)}"
        if pip_multiplier == 100:
            return f"{round(price_diff * pip_multiplier, 1)} pip"
    return f"{round(price_diff * pip_multiplier, 1)} point"


def _build_execution_zone(current_price, atr_h1, fallback_zone):
    if current_price is None:
        return fallback_zone
    if atr_h1 is not None and atr_h1 > 0:
        half_width = atr_h1 * EXECUTION_ATR_RATIO
        return [
            round(current_price - half_width, 5),
            round(current_price + half_width, 5),
        ]
    return fallback_zone


STALE_ZONE_RATIO = 1.0


def _check_zone_validity(current_price, zone):
    if current_price is None or not zone or len(zone) != 2:
        return True
    zone_low, zone_high = sorted(zone)
    width = zone_high - zone_low
    if width <= 0:
        return True
    if current_price < zone_low:
        return (zone_low - current_price) <= (width * STALE_ZONE_RATIO)
    if current_price > zone_high:
        return (current_price - zone_high) <= (width * STALE_ZONE_RATIO)
    return True


def build_trade_setup(
    recommendation,
    elliott,
    fib,
    pivots,
    wave_context,
    current_price: float = None,
    atr_h1: float = None,
    pip_multiplier: float = 10000,
    h1_pivots: dict | None = None,
    d1_pivots: dict | None = None,
):
    """
    يبني خطة التداول الكاملة مع ثلاثة مستويات للـ Stop Loss:

        trade_stop        : SL تكتيكي (H1 ATR) — يُثبَّت وقت الإشارة
        structural_stop   : SL هيكلي  (D1 swing) — يتغير نادراً
        catastrophic_stop : SL كارثي  (أقصى/أدنى W1) — يلغي السيناريو كله

    FIX (هذه النسخة):
        _calc_structural_stop_buy/_sell أصبحتا تبحثان عن أحدث pivot
        يكون فعلياً على الجهة الصحيحة من السعر الحالي (نفس منطق
        invalidation تماماً)، بدل أخذ آخر pivot مسجَّل بغض النظر عن
        موقعه — هذا كان يسبب أحياناً ظهور structural_stop أقرب من
        trade_stop (ترتيب معكوس منطقياً، الستوب "الهيكلي" المفترض
        أبعد كان يظهر أقرب من الستوب "التكتيكي").

        بالإضافة لحماية صريحة نهائية: إذا تبيّن structural_stop أقرب
        من trade_stop رغم الإصلاح أعلاه (حالة نادرة، مثلاً لو D1 pivot
        الوحيد المتاح أقرب فعلياً من H1 pivot)، نضمن السلامة المنطقية
        بأخذ القيمة الأبعد بينهما كـ structural_stop النهائي — حتى لا
        يظهر ترتيب معكوس مهما كانت بيانات الـ pivots.
    """

    direction = recommendation.get("direction", "neutral")

    w1_highs = pivots.get("highs", [])
    w1_lows  = pivots.get("lows",  [])

    h1_pivots = h1_pivots or {}
    h1_highs  = h1_pivots.get("highs", [])
    h1_lows   = h1_pivots.get("lows",  [])

    d1_pivots = d1_pivots or {}
    d1_highs  = d1_pivots.get("highs", [])
    d1_lows   = d1_pivots.get("lows",  [])

    if not w1_highs or not w1_lows:
        return {"status": "invalid_setup"}

    expected_wave = wave_context.get("next_expected", "unknown")
    signal        = recommendation["signal"]
    is_immediate  = signal in IMMEDIATE_SIGNALS

    setup = {
        "signal"             : signal,
        "direction"          : direction,
        "expected_wave"      : expected_wave,
        "strategic_zone"     : [],
        "execution_zone"     : [],
        "entry_zone"         : [],
        "zone_valid"         : True,
        "trade_stop"         : None,   # SL تكتيكي — ثابت بعد الإشارة
        "structural_stop"    : None,   # SL هيكلي  — D1 swing
        "structural_stop_source": None,
        "catastrophic_stop"  : None,   # SL كارثي  — أقصى/أدنى W1
        "invalidation"       : None,   # = trade_stop (توافق مع السابق)
        "invalidation_method": None,
        "atr_h1"             : atr_h1,
        "pip_multiplier"     : pip_multiplier,
        "targets"            : [],
        "current_price"      : current_price,
        "distance_pips"      : None,
        "distance_label"     : None,
        "entry_status"       : None,
    }

    # --------------------
    # SELL SETUP
    # --------------------

    if direction == "sell":

        # CHANGE (تضييق entry_zone): نطاق أضيق حول 38.2%-50%
        fib_382 = _get_fib_level(fib, "38.2")
        fib_236 = _get_fib_level(fib, "23.6")
        fib_50 = _get_fib_level(
            fib, "50",
            fallback=(fib_382 + fib_236) / 2 if (fib_382 is not None and fib_236 is not None) else None,
        )

        atr_buffer = (atr_h1 * EXECUTION_ATR_RATIO) if (atr_h1 is not None and atr_h1 > 0) else 0

        if fib_382 is not None and fib_50 is not None:
            entry_high = fib_382 + atr_buffer
            entry_low  = fib_50 - atr_buffer
        else:
            # احتياطي: السلوك القديم لو المستويات غير متاحة بالكامل
            entry_high = fib["retracement"]["23.6"]
            entry_low  = fib["retracement"]["38.2"]

        strategic_zone = [entry_low, entry_high]

        execution_zone = (
            _build_execution_zone(current_price, atr_h1, strategic_zone)
            if is_immediate else strategic_zone
        )

        zone_valid = is_immediate or _check_zone_validity(current_price, strategic_zone)
        setup["zone_valid"] = zone_valid

        setup["strategic_zone"] = strategic_zone
        if zone_valid:
            setup["execution_zone"] = execution_zone
            setup["entry_zone"]     = strategic_zone
        else:
            setup["execution_zone"] = []
            setup["entry_zone"]     = []

        tactical, t_method = _calc_invalidation_sell(current_price, h1_highs, w1_highs, atr_h1)
        structural, s_source = _calc_structural_stop_sell(current_price, d1_highs, w1_highs, atr_h1)
        catastrophic         = _calc_catastrophic_stop_sell(w1_highs)

        # حماية نهائية صريحة: structural يجب يكون أبعد من tactical (أعلى
        # في sell). لو لم يكن كذلك (حالة نادرة)، نأخذ الأبعد بينهما.
        if structural is not None and tactical is not None and structural < tactical:
            structural = tactical
            s_source = f"{s_source} (مُعدَّل ليكون أبعد من trade_stop)"

        setup["trade_stop"]          = tactical
        setup["structural_stop"]     = structural
        setup["structural_stop_source"] = s_source
        setup["catastrophic_stop"]   = catastrophic
        setup["invalidation"]        = tactical
        setup["invalidation_method"] = t_method

        # FIX (targets): مرجع الفلترة هو حد منطقة الدخول السفلي، لا current_price
        targets_reference = (
            execution_zone[0] if execution_zone else current_price
        )

        setup["targets"] = _build_targets_sell(
            targets_reference, h1_lows, w1_lows, fib.get("swing_low")
        )

        # حماية إضافية: استبعاد أي target لا يزال أعلى من حد الدخول
        if setup["entry_zone"]:
            zone_low_guard = min(setup["entry_zone"])
            setup["targets"] = [t for t in setup["targets"] if t < zone_low_guard]

        if current_price is not None:
            zone_low, zone_high = execution_zone
            zone_mid   = round((zone_low + zone_high) / 2, 5)
            price_diff = abs(current_price - zone_mid)
            setup["distance_pips"]  = round(price_diff * pip_multiplier, 1)
            setup["distance_label"] = format_distance(price_diff, pip_multiplier, reference_price=current_price)

            if zone_low <= current_price <= zone_high:
                setup["entry_status"] = f"في منطقة الدخول (mid: {zone_mid})"
            elif current_price > zone_high:
                setup["entry_status"] = (
                    f"السعر فوق المنطقة بـ {setup['distance_label']} "
                    f"— انتظر تراجع لـ {zone_mid}"
                )
            elif is_immediate:
                setup["entry_status"] = (
                    f"السعر تجاوز منطقة التنفيذ هبوطاً بـ {setup['distance_label']} "
                    f"— الإشارة منتهية"
                )
            else:
                ctx = recommendation.get("context", "")
                setup["entry_status"] = (
                    f"السعر تجاوز منطقة فيبوناتشي W1 (الإستراتيجية) هبوطاً "
                    f"بـ {setup['distance_label']} — هذه المنطقة لم تعد ذات صلة. "
                    f"التوصية الحالية تعتمد على السياق الفراكتلي: {ctx}"
                )

    # --------------------
    # BUY SETUP
    # --------------------

    elif direction == "buy":

        # CHANGE (تضييق entry_zone): نطاق أضيق حول 50%-61.8%
        fib_618 = _get_fib_level(fib, "61.8")
        fib_382 = _get_fib_level(fib, "38.2")
        fib_50 = _get_fib_level(
            fib, "50",
            fallback=(fib_618 + fib_382) / 2 if (fib_618 is not None and fib_382 is not None) else None,
        )

        atr_buffer = (atr_h1 * EXECUTION_ATR_RATIO) if (atr_h1 is not None and atr_h1 > 0) else 0

        if fib_618 is not None and fib_50 is not None:
            entry_low  = fib_618 - atr_buffer
            entry_high = fib_50 + atr_buffer
        else:
            # احتياطي: لو مستويات فيبوناتشي غير متاحة بالكامل
            entry_low  = fib["retracement"]["61.8"]
            entry_high = fib["retracement"]["38.2"]

        strategic_zone = [entry_low, entry_high]

        execution_zone = (
            _build_execution_zone(current_price, atr_h1, strategic_zone)
            if is_immediate else strategic_zone
        )

        zone_valid = is_immediate or _check_zone_validity(current_price, strategic_zone)
        setup["zone_valid"] = zone_valid

        setup["strategic_zone"] = strategic_zone
        if zone_valid:
            setup["execution_zone"] = execution_zone
            setup["entry_zone"]     = strategic_zone
        else:
            setup["execution_zone"] = []
            setup["entry_zone"]     = []

        tactical, t_method = _calc_invalidation_buy(current_price, h1_lows, w1_lows, atr_h1)
        structural, s_source = _calc_structural_stop_buy(
            current_price, d1_lows, w1_lows, atr_h1,
            tactical_stop=tactical,
        )
        catastrophic         = _calc_catastrophic_stop_buy(w1_lows)

        # حماية نهائية صريحة: structural يجب يكون أبعد من tactical (أدنى
        # في buy). لو لم يكن كذلك (حالة نادرة)، نأخذ الأبعد بينهما.
        if structural is not None and tactical is not None and structural > tactical:
            structural = tactical
            s_source = f"{s_source} (مُعدَّل ليكون أبعد من trade_stop)"

        setup["trade_stop"]          = tactical
        setup["structural_stop"]     = structural
        setup["structural_stop_source"] = s_source
        setup["catastrophic_stop"]   = catastrophic
        setup["invalidation"]        = tactical
        setup["invalidation_method"] = t_method

        # FIX (الخطأ الأساسي الذي رصدناه): مرجع الفلترة هو حد منطقة الدخول
        # العلوي، لا current_price — يمنع مرور أهداف خلف نقطة الدخول.
        targets_reference = (
            execution_zone[1] if execution_zone else current_price
        )

        setup["targets"] = _build_targets_buy(
            targets_reference, h1_highs, w1_highs,
            fib.get("extension", {}).get("127.2"),
            fib=fib,
            entry_zone_high=execution_zone[1] if execution_zone else None,
        )

        # حماية إضافية: استبعاد أي target لا يزال أقل من حد الدخول
        if setup["entry_zone"]:
            zone_high_guard = max(setup["entry_zone"])
            setup["targets"] = [t for t in setup["targets"] if t > zone_high_guard]

        if current_price is not None:
            zone_low, zone_high = execution_zone
            zone_mid   = round((zone_low + zone_high) / 2, 5)
            price_diff = abs(current_price - zone_mid)
            setup["distance_pips"]  = round(price_diff * pip_multiplier, 1)
            setup["distance_label"] = format_distance(price_diff, pip_multiplier, reference_price=current_price)

            if zone_low <= current_price <= zone_high:
                setup["entry_status"] = f"في منطقة الدخول (mid: {zone_mid})"
            elif current_price < zone_low:
                setup["entry_status"] = (
                    f"السعر تحت المنطقة بـ {setup['distance_label']} "
                    f"— انتظر ارتداد لـ {zone_mid}"
                )
            elif is_immediate:
                setup["entry_status"] = (
                    f"السعر تجاوز منطقة التنفيذ صعوداً بـ {setup['distance_label']} "
                    f"— الإشارة منتهية"
                )
            else:
                ctx = recommendation.get("context", "")
                setup["entry_status"] = (
                    f"السعر تجاوز منطقة فيبوناتشي W1 (الإستراتيجية) صعوداً "
                    f"بـ {setup['distance_label']} — هذه المنطقة لم تعد ذات صلة. "
                    f"التوصية الحالية تعتمد على السياق الفراكتلي: {ctx}"
                )

    return setup