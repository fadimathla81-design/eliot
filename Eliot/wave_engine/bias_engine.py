# wave_engine/bias_engine.py
"""
محرك Bias موحّد — single source of truth.

CHANGE (إصلاح تعدد مصادر Bias): قبل هذا الملف، كان هناك مصدران
منفصلان لحساب الـ bias لأي فريم:

    1. wave_bias.get_wave_bias() — يفحص فقط `"bullish_impulse"` أو
       `"bearish_impulse"` بمطابقة حرفية. أي نمط آخر (ABC, zigzag,
       flat, triangle) يُرجع "neutral" بلا استثناء — حتى لو كان
       الفريم في تصحيح واضح الاتجاه بناءً على الأسعار الفعلية.

    2. conflict_resolver._bias_of() — يفحص الاسم الحرفي أولاً، وإن لم
       يجد اتجاهاً به، يستخدم `direction` الفعلي (up/down) المحسوب من
       الأسعار الخام.

    النتيجتان كانتا تظهران معاً في نفس التقرير (قسم BIASES يطبع
    "neutral" من المصدر الأول، بينما recommendation.primary_bias يطبع
    "bullish" من المصدر الثاني) — تماماً نفس مشكلة تعدد مصادر Elliott
    التي حُلّت سابقاً، لكن لمفهوم الـ bias.

    الآن: get_bias() هنا هو الدالة الوحيدة لحساب bias في كل النظام.
    wave_bias.py لم يعد يُستخدم؛ يُفضّل حذف استدعاءاته بالكامل.
"""

# نفس التصنيفات المستخدمة في conflict_resolver.py و wave_alignment.py
BEARISH_PATTERNS    = {"bearish_impulse", "bearish_ABC"}
BULLISH_PATTERNS    = {"bullish_impulse", "bullish_ABC"}
CORRECTION_PATTERNS = {"ABC", "zigzag", "flat", "triangle"}

# نفس العتبة المستخدمة في conflict_resolver.py لاعتبار فريم "نشطاً"
MIN_ACTIVE_CONFIDENCE = 30


def get_bias(pattern: str, direction: str | None = None, confidence: float | None = None) -> str:
    """
    يحدد bias فعلي ("bullish" / "bearish" / "neutral") لأي pattern.

    الأولوية:
        1. إذا كان pattern غير محدد (unknown/فاضي) أو confidence أقل
           من MIN_ACTIVE_CONFIDENCE → "neutral" (بيانات غير كافية).
        2. إذا كان اسم الـ pattern نفسه يحمل اتجاهاً واضحاً
           (bullish_impulse, bearish_impulse, bullish_ABC, bearish_ABC)
           → استخدمه مباشرة.
        3. غير ذلك (zigzag/flat/triangle/ABC العامة) → استخدم
           `direction` الفعلي (up/down) المحسوب من الأسعار الخام.
        4. لو لا اتجاه بالاسم ولا direction متاح → "neutral".

    Args:
        pattern    : اسم النمط من elliott["pattern"]
        direction  : "up"/"down"/None — من wave_map[tf]["direction"]
        confidence : 0-100 — من elliott["confidence"]

    Returns:
        "bullish" | "bearish" | "neutral"
    """
    if pattern in ("unknown", "", None):
        return "neutral"

    if confidence is not None and confidence < MIN_ACTIVE_CONFIDENCE:
        return "neutral"

    if "bullish_impulse" in pattern or pattern == "bullish_ABC":
        return "bullish"
    if "bearish_impulse" in pattern or pattern == "bearish_ABC":
        return "bearish"

    if direction == "up":
        return "bullish"
    if direction == "down":
        return "bearish"

    return "neutral"


def get_bias_from_elliott(elliott: dict, direction: str | None = None) -> str:
    """
    نسخة مريحة تأخذ dict كامل من نوع elliott (كما يُخزَّن في
    wave_map[tf]["elliott"]) بدل تفكيك pattern/confidence يدوياً.

    Args:
        elliott   : dict يحتوي "pattern" و"confidence" على الأقل
        direction : "up"/"down"/None — من wave_map[tf]["direction"]
    """
    if not elliott:
        return "neutral"

    pattern    = elliott.get("pattern", "")
    confidence = elliott.get("confidence", 0)

    return get_bias(pattern, direction, confidence)


def get_next_bias(elliott: dict, direction: str | None = None) -> str:
    """
    يحدد bias الموجة التالية المتوقعة — يُستخدم بعد اكتمال impulse أو
    تصحيح كامل، عندما يُتوقع انعكاس الاتجاه.

    CHANGE: نفس منطق wave_bias.get_next_wave_bias() القديم، لكن مبني
    على get_bias_from_elliott() الموحّدة بدل المطابقة الحرفية فقط،
    فيعمل أيضاً مع zigzag/flat/triangle لا فقط *_impulse الحرفية.

    المنطق:
        - لو الفريم انتهى من impulse (wave_5 → next=wave_A) →
          bias التالي هو عكس bias الحالي (الاتجاه ينعكس مع التصحيح).
        - لو الفريم انتهى من تصحيح كامل (wave_C → next=trend_resumption) →
          bias التالي هو نفس bias الحالي (استئناف نفس الاتجاه الأصلي).
        - غير ذلك → "neutral" (لا انعكاس متوقع حالياً).
    """
    if not elliott:
        return "neutral"

    current_bias = get_bias_from_elliott(elliott, direction)
    if current_bias == "neutral":
        return "neutral"

    current_wave = elliott.get("current_wave", "")
    next_wave    = elliott.get("next_wave", "")
    pattern      = elliott.get("pattern", "")

    opposite = "bearish" if current_bias == "bullish" else "bullish"

    # impulse اكتمل (wave_5) ومتوقع تصحيح (wave_A) → الاتجاه ينعكس
    if current_wave == "wave_5" and next_wave == "wave_A":
        return opposite

    # تصحيح اكتمل (wave_C) ومتوقع استئناف الاتجاه الأصلي
    if (
        pattern in CORRECTION_PATTERNS
        and current_wave == "wave_C"
        and next_wave == "trend_resumption"
    ):
        return current_bias

    return "neutral"