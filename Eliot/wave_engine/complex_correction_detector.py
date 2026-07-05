# wave_engine/complex_correction_detector.py
"""
كشف الأنماط التصحيحية المعقدة في نظرية إليوت — الخطوة الأولى: Zigzag.

السياق المعماري (لماذا هذا الملف موجود):
classify_wave() الحالي (wave_classifier.py) يختزل كل التصحيحات إلى "ABC"
بسيط: نقطة واحدة لكل من A وB وC، بدون أي فحص للبنية الداخلية. هذا يعني
حتى لو كان التصحيح الفعلي زigzag حقيقي (حيث A وC أنفسهما عبارة عن 5 موجات
دفعية داخلية)، النظام الحالي يصنّفه كنقطة A/B/C بسيطة فقط.

هذا الملف هو الخطوة الأولى من مشروع أكبر (دعم Zigzag/Flat/Triangle/W-X-Y)،
يُبنى تدريجياً خطوة بخطوة بدون استعجال، كل خطوة مُختبرة بمعزل قبل الانتقال
للتالية.

قرار الترتيب (fail-strict-first):
نحاول تصنيف التصحيح كـ Zigzag أولاً (الشرط الأكثر تشدداً: A وC يجب أن
يحققا قواعد إليوت الدفعية الصحيحة كما في elliott_rules_validator.py)،
ونتراجع لـ ABC البسيط فقط إذا فشل الفحص الصارم. هذا يقلل الأخطاء الكاذبة:
أي Zigzag حقيقي هو بالتعريف أيضاً ABC صحيح، لكن العكس غير صحيح، فالفحص
الأكثر تشدداً يجب أن يُجرَّب أولاً.

هذا الملف لا يستبدل classify_wave ولا correction_detector — يُستدعى
كخطوة اختيارية قبلهما (integration point لاحق، غير مُفعَّل بعد).
"""

# نفس نسب فيبوناتشي المستخدمة في correction_detector.py للتناسق،
# لكن مطبّقة هنا على طول الموجتين A وC الكاملتين (لا نقطة واحدة).
ZIGZAG_WAVE_C_MIN_RATIO = 0.618
ZIGZAG_WAVE_C_MAX_RATIO = 1.80

# الحد الأدنى لعدد نقاط swing اللازمة لتشكيل موجة دفعية فرعية (5 موجات
# = 5 نقاط متعاقبة على الأقل، بما يطابق طول sequence في
# validate_elliott_rules).
MIN_IMPULSE_POINTS = 5


def _validate_impulse_structure(points: list) -> dict:
    """
    يفحص هل 5 نقاط متعاقبة تشكّل موجة دفعية صحيحة حسب قواعد إليوت
    الأساسية (wave3 ليست الأقصر، wave4 لا تتداخل مع wave1، wave5 ليست
    ممتدة جداً). هذا نفس منطق validate_elliott_rules تماماً (لم نستورده
    مباشرة لتجنب أي تبعية دائرية محتملة بين الملفين، والمنطق مستقر
    ومختصر بما يكفي لإعادة كتابته محلياً بأمان).

    Args:
        points: قائمة من 5 نقاط swing متعاقبة بالضبط.

    Returns:
        {"valid": bool, "score": int, "direction": "up"|"down"|None}
    """
    if len(points) != MIN_IMPULSE_POINTS:
        return {"valid": False, "score": 0, "direction": None}

    p1 = points[0]["price"]
    p2 = points[1]["price"]
    p3 = points[2]["price"]
    p4 = points[3]["price"]
    p5 = points[4]["price"]

    score = 100

    if p1 > p3 > p5:
        direction = "down"
        wave1 = abs(p2 - p1)
        wave3 = abs(p4 - p3)
        wave5 = abs(p4 - p5)

        if wave3 < min(wave1, wave5):
            score -= 35
        if p4 >= p1:
            score -= 25
        if wave3 > 0 and wave5 > wave3 * 1.618:
            score -= 10

        return {"valid": score >= 50, "score": max(score, 0), "direction": direction}

    if p1 < p3 < p5:
        direction = "up"
        wave1 = abs(p2 - p1)
        wave3 = abs(p4 - p3)
        wave5 = abs(p5 - p4)

        if wave3 < min(wave1, wave5):
            score -= 35
        if p4 <= p1:
            score -= 25
        if wave3 > 0 and wave5 > wave3 * 1.618:
            score -= 10

        return {"valid": score >= 50, "score": max(score, 0), "direction": direction}

    return {"valid": False, "score": 20, "direction": None}


def _find_swing_after(swings: list, after_index: int, want_type: str):
    """أول swing بعد after_index يطابق want_type (HIGH/LOW)."""
    for s in swings:
        if s["index"] > after_index and s["type"] == want_type:
            return s
    return None


def detect_zigzag(swings: list, correction_start: dict) -> dict:
    """
    يحاول تصنيف التصحيح الجاري (الذي يبدأ من correction_start) كـ Zigzag
    (5-3-5)، بفحص هل أول 5 نقاط بعد correction_start تشكّل موجة A دفعية
    صحيحة، ثم نقطة B تصحيحية، ثم 5 نقاط أخرى تشكّل موجة C دفعية صحيحة.

    Args:
        swings: التسلسل الكامل لـ swings (نفس البنية من
                swing_structure.build_swing_sequence).
        correction_start: نقطة البداية (نفس correction_start الممرّر
                إلى correction_detector.detect_correction حالياً).

    Returns:
        إذا تحقق الشكل بالكامل بنسب فيبوناتشي صحيحة:
        {
            "pattern": "zigzag",
            "current_wave": "wave_A" | "wave_B" | "wave_C",
            "next_expected": "wave_B" | "wave_C" | "impulse",
            "subwave": None | "wave_5",  # نفس تسمية ABC الحالية للتوافق
            "confidence": int,
            "wave_a_points": list,  # للتشخيص/الاختبار
            "wave_c_points": list | None,
        }

        إذا فشل الفحص الصارم في أي مرحلة:
        {"pattern": "unknown", "reason": "..."}
        (المستدعي يجب أن يتراجع لمنطق ABC البسيط الحالي عند هذه النتيجة)
    """
    if not correction_start or not swings:
        return {"pattern": "unknown", "reason": "no_correction_start_or_swings"}

    start_idx  = correction_start["index"]
    start_type = correction_start["type"]

    # نقاط ما بعد correction_start فقط، مرتبة بالـ index (swings مرتبة
    # أصلاً من build_swing_sequence، لكن نتأكد بأمان).
    after = sorted(
        [s for s in swings if s["index"] > start_idx],
        key=lambda s: s["index"],
    )

    # موجة A المتوقعة تبدأ بنفس عكس نوع correction_start (نفس قاعدة
    # a_end_type في correction_detector.py: HIGH→LOW أو LOW→HIGH).
    a_end_type = "HIGH" if start_type == "LOW" else "LOW"

    # ── محاولة بناء موجة A من 5 نقاط دفعية (correction_start + أول 4
    # نقاط بعده، أي 5 نقاط إجمالاً تبدأ من نقطة البداية نفسها) ──────
    wave_a_candidate = [correction_start] + after[:MIN_IMPULSE_POINTS - 1]

    if len(wave_a_candidate) < MIN_IMPULSE_POINTS:
        return {"pattern": "unknown", "reason": "insufficient_points_for_wave_a"}

    a_check = _validate_impulse_structure(wave_a_candidate)
    if not a_check["valid"]:
        return {"pattern": "unknown", "reason": "wave_a_not_impulsive", "score": a_check["score"]}

    wave_a_end = wave_a_candidate[-1]

    # ── موجة A انتهت — الآن نبحث عن B (نفس نوع correction_start، نقطة
    # تصحيحية واحدة، بنفس قاعدة b_end_type في correction_detector.py) ─
    b_end_type = start_type
    wave_b_end = _find_swing_after(swings, wave_a_end["index"], b_end_type)

    if not wave_b_end:
        return {
            "pattern": "zigzag",
            "current_wave": "wave_A",
            "next_expected": "wave_B",
            "subwave": None,
            "confidence": a_check["score"],
            "wave_a_points": wave_a_candidate,
            "wave_c_points": None,
        }

    # ── موجة B انتهت — الآن نحاول بناء موجة C من 5 نقاط دفعية بعدها ──
    points_after_b = sorted(
        [s for s in swings if s["index"] > wave_b_end["index"]],
        key=lambda s: s["index"],
    )
    wave_c_candidate = [wave_b_end] + points_after_b[:MIN_IMPULSE_POINTS - 1]

    if len(wave_c_candidate) < MIN_IMPULSE_POINTS:
        return {
            "pattern": "zigzag",
            "current_wave": "wave_B",
            "next_expected": "wave_C",
            "subwave": None,
            "confidence": a_check["score"],
            "wave_a_points": wave_a_candidate,
            "wave_c_points": None,
        }

    c_check = _validate_impulse_structure(wave_c_candidate)
    if not c_check["valid"]:
        return {"pattern": "unknown", "reason": "wave_c_not_impulsive", "score": c_check["score"]}

    wave_c_end = wave_c_candidate[-1]

    # ── التحقق من نسب فيبوناتشي بين طول A الكامل وطول C الكامل ──────
    a_len = abs(wave_a_end["price"] - correction_start["price"])
    c_len = abs(wave_c_end["price"] - wave_b_end["price"])

    if a_len == 0:
        return {"pattern": "unknown", "reason": "zero_length_wave_a"}

    c_ratio = c_len / a_len
    ratio_valid = ZIGZAG_WAVE_C_MIN_RATIO <= c_ratio <= ZIGZAG_WAVE_C_MAX_RATIO

    if not ratio_valid:
        return {
            "pattern": "zigzag",
            "current_wave": "wave_C",
            "next_expected": "impulse",
            "subwave": None,  # لم تتحقق النسبة — لا نعلن اكتمالاً واثقاً
            "confidence": 65,
            "wave_a_points": wave_a_candidate,
            "wave_c_points": wave_c_candidate,
            "c_ratio": round(c_ratio, 4),
        }

    confidence = int((a_check["score"] + c_check["score"]) / 2)

    return {
        "pattern": "zigzag",
        "current_wave": "wave_C",
        "next_expected": "impulse",
        "subwave": "wave_5",  # نفس تسمية ABC الحالية — يعني الاكتمال محقق
        "confidence": confidence,
        "wave_a_points": wave_a_candidate,
        "wave_c_points": wave_c_candidate,
        "c_ratio": round(c_ratio, 4),
    }


# ---------------------------------------------------------------------------
# الخطوة الثالثة من المشروع: Flat (3-3-5)
# ---------------------------------------------------------------------------
"""
الفرق الجوهري عن Zigzag:
- موجة A في Flat ليست دفعية (3 نقاط تصحيحية بسيطة، لا 5 نقاط دفعية).
- موجة B ترتد بنسبة قريبة جداً من 100% من A (لا تتجاوز 100% بكثير في
  الـ Regular Flat — هذا ما يميزها عن Zigzag حيث B لا تتجاوز 100% أبداً
  عادة لكن غالباً أقل بكثير، بينما في Flat تقترب من الحد).
- موجة C دفعية (5 نقاط)، نفس فحص Zigzag تماماً.

نبدأ بـ Regular Flat فقط (B في نطاق 0.78-1.05 من A تقريباً) — أبسط
وأكثر شيوعاً. Expanded/Running Flat تحتاج جلسات لاحقة (نطاقات نسب
مختلفة، يمكن البناء عليها بتعديل الثوابت أدناه دون إعادة كتابة المنطق).
"""

FLAT_WAVE_B_MIN_RATIO = 0.78
FLAT_WAVE_B_MAX_RATIO = 1.05

# نفس نطاق نسبة C المستخدم في Zigzag — مشترك بين الشكلين لأن موجة C
# في كليهما دفعية بنفس الطبيعة.
FLAT_WAVE_C_MIN_RATIO = 0.618
FLAT_WAVE_C_MAX_RATIO = 1.80

# طول موجة A التصحيحية البسيطة في Flat: 3 نقاط (بداية + ارتداد + نهاية)،
# على عكس 5 نقاط الدفعية في Zigzag.
FLAT_WAVE_A_POINTS = 3


def _validate_simple_correction(points: list) -> dict:
    """
    يفحص هل 3 نقاط متعاقبة تشكّل تصحيحاً بسيطاً صحيحاً (لا دفعياً):
    حركة واحدة بوضوح في اتجاه معاكس لاتجاه الموجة الأكبر، بدون كسر
    منطقي (النقطة الوسطى لا تتجاوز نقطتي البداية والنهاية).

    هذا أبسط بكثير من _validate_impulse_structure لأن موجة A في Flat
    ليست تركيبة 5 موجات، هي فقط حركة تصحيحية واحدة (3-3-5 يعني موجة A
    نفسها "3" أي تصحيحية بسيطة، تماماً كموجة B في ABC العادي).

    Args:
        points: قائمة من 3 نقاط swing متعاقبة بالضبط [بداية، وسط، نهاية].

    Returns:
        {"valid": bool, "score": int}
    """
    if len(points) != FLAT_WAVE_A_POINTS:
        return {"valid": False, "score": 0}

    p1 = points[0]["price"]
    p2 = points[1]["price"]
    p3 = points[2]["price"]

    # حركة هابطة بسيطة: p1 > p2، وp3 يجب أن يكون أبعد من p2 بنفس اتجاه
    # الحركة العامة (p3 < p1) لتشكّل تصحيحاً واحداً واضحاً، لا تذبذباً.
    if p1 > p2 and p3 < p1:
        return {"valid": True, "score": 80}

    # حركة صاعدة بسيطة (نفس المنطق بعكس الاتجاه)
    if p1 < p2 and p3 > p1:
        return {"valid": True, "score": 80}

    return {"valid": False, "score": 20}


def detect_flat(swings: list, correction_start: dict) -> dict:
    """
    يحاول تصنيف التصحيح الجاري كـ Regular Flat (3-3-5)، بفحص هل أول 3
    نقاط بعد correction_start تشكّل موجة A تصحيحية بسيطة، ثم نقطة B
    ترتد بنسبة قريبة من 100% من A (لا نقطة B بنسبة أقل بكثير كما في
    Zigzag)، ثم 5 نقاط تشكّل موجة C دفعية صحيحة.

    Args:
        swings: التسلسل الكامل لـ swings.
        correction_start: نقطة البداية (نفس correction_start المستخدم
                مع detect_zigzag وcorrection_detector.detect_correction).

    Returns:
        نفس بنية detect_zigzag تماماً (pattern="flat" بدل "zigzag")،
        لضمان توافق سهل عند الربط مع wave_classifier/elliott_wave_engine.
        فشل الفحص الصارم في أي مرحلة → {"pattern": "unknown", "reason": "..."}
    """
    if not correction_start or not swings:
        return {"pattern": "unknown", "reason": "no_correction_start_or_swings"}

    start_idx  = correction_start["index"]
    start_type = correction_start["type"]

    after = sorted(
        [s for s in swings if s["index"] > start_idx],
        key=lambda s: s["index"],
    )

    # ── محاولة بناء موجة A من 3 نقاط تصحيحية بسيطة فقط ───────────────
    wave_a_candidate = [correction_start] + after[:FLAT_WAVE_A_POINTS - 1]

    if len(wave_a_candidate) < FLAT_WAVE_A_POINTS:
        return {"pattern": "unknown", "reason": "insufficient_points_for_wave_a"}

    a_check = _validate_simple_correction(wave_a_candidate)
    if not a_check["valid"]:
        return {"pattern": "unknown", "reason": "wave_a_not_corrective", "score": a_check["score"]}

    wave_a_end = wave_a_candidate[-1]

    # ── موجة A انتهت — نبحث عن B (نفس نوع correction_start) ──────────
    b_end_type = start_type
    wave_b_end = _find_swing_after(swings, wave_a_end["index"], b_end_type)

    if not wave_b_end:
        return {
            "pattern": "flat",
            "current_wave": "wave_A",
            "next_expected": "wave_B",
            "subwave": None,
            "confidence": a_check["score"],
            "wave_a_points": wave_a_candidate,
            "wave_c_points": None,
        }

    # ── فحص نسبة B/A فوراً (الفارق الجوهري عن Zigzag): إذا B بعيدة عن
    # نطاق Flat (قريبة من 100%)، هذا ليس Flat حقيقياً — نفشل بأمان هنا
    # بدل الاستمرار وبناء C على أساس خاطئ.
    a_len = abs(wave_a_end["price"] - correction_start["price"])
    if a_len == 0:
        return {"pattern": "unknown", "reason": "zero_length_wave_a"}

    b_len = abs(wave_b_end["price"] - wave_a_end["price"])
    b_ratio = b_len / a_len

    if not (FLAT_WAVE_B_MIN_RATIO <= b_ratio <= FLAT_WAVE_B_MAX_RATIO):
        return {
            "pattern": "unknown",
            "reason": "wave_b_ratio_not_flat",
            "b_ratio": round(b_ratio, 4),
        }

    # ── موجة B تحققت كنسبة Flat — نحاول بناء موجة C من 5 نقاط دفعية ──
    points_after_b = sorted(
        [s for s in swings if s["index"] > wave_b_end["index"]],
        key=lambda s: s["index"],
    )
    wave_c_candidate = [wave_b_end] + points_after_b[:MIN_IMPULSE_POINTS - 1]

    if len(wave_c_candidate) < MIN_IMPULSE_POINTS:
        return {
            "pattern": "flat",
            "current_wave": "wave_B",
            "next_expected": "wave_C",
            "subwave": None,
            "confidence": a_check["score"],
            "wave_a_points": wave_a_candidate,
            "wave_c_points": None,
            "b_ratio": round(b_ratio, 4),
        }

    c_check = _validate_impulse_structure(wave_c_candidate)
    if not c_check["valid"]:
        return {"pattern": "unknown", "reason": "wave_c_not_impulsive", "score": c_check["score"]}

    wave_c_end = wave_c_candidate[-1]

    # ── التحقق من نسبة C الكاملة إلى A الكاملة ───────────────────────
    c_len = abs(wave_c_end["price"] - wave_b_end["price"])
    c_ratio = c_len / a_len
    ratio_valid = FLAT_WAVE_C_MIN_RATIO <= c_ratio <= FLAT_WAVE_C_MAX_RATIO

    if not ratio_valid:
        return {
            "pattern": "flat",
            "current_wave": "wave_C",
            "next_expected": "impulse",
            "subwave": None,
            "confidence": 65,
            "wave_a_points": wave_a_candidate,
            "wave_c_points": wave_c_candidate,
            "b_ratio": round(b_ratio, 4),
            "c_ratio": round(c_ratio, 4),
        }

    confidence = int((a_check["score"] + c_check["score"]) / 2)

    return {
        "pattern": "flat",
        "current_wave": "wave_C",
        "next_expected": "impulse",
        "subwave": "wave_5",
        "confidence": confidence,
        "wave_a_points": wave_a_candidate,
        "wave_c_points": wave_c_candidate,
        "b_ratio": round(b_ratio, 4),
        "c_ratio": round(c_ratio, 4),
    }


# ---------------------------------------------------------------------------
# الخطوة الرابعة من المشروع: Triangle (3-3-3-3-3)
# ---------------------------------------------------------------------------
"""
الفرق الجوهري عن Zigzag/Flat:
- Triangle له 5 موجات (A-B-C-D-E)، لا 3. كل موجة هي نقطة swing واحدة
  فقط (لا تركيبة فرعية من 5 أو 3 نقاط كما في Zigzag/Flat) — التحقق
  الأساسي هنا ليس نسب فيبوناتشي بين موجتين، بل انكماش تدريجي في مدى
  السعر عبر الموجات المتتالية.
- الأنواع الثلاثة (Symmetrical/Ascending/Descending) تتشارك نفس الفحص
  الأساسي (تضييق متتالي)، وتختلف فقط في أي طرف من النطاق يبقى مستوياً
  تقريباً (القمم فقط، القواعد فقط، أو كلاهما يتحرك تقارباً).

بنية Triangle المتوقعة (assuming correction_start = HIGH، تصحيح هابط
أولاً تنازلياً ثم يتذبذب):
    A (LOW), B (HIGH), C (LOW), D (HIGH), E (LOW)
كل قمة جديدة (B, D) أقل من أو تساوي تقريباً القمة السابقة (الأصل، B).
كل قاع جديد (A, C, E) أعلى من أو يساوي تقريباً القاع السابق.

لاحظ: على عكس Zigzag/Flat، correction_start نفسه هو الموجة "0" (نقطة
الانعكاس الأصلية)، وA هي أول swing بعدها — هذا يعني نحتاج 5 نقاط بعد
correction_start (لا تتضمن correction_start ضمن نقاط A-E نفسها، خلافاً
لمعالجة Zigzag/Flat حيث correction_start هو نفسه أول نقطة في wave_a).
"""

# نسبة الانكماش المقبولة بين موجة وسابقتها المتجانسة (مثل B مقارنة بـ
# القمة الأصلية، D مقارنة بـB). يجب أن يكون النطاق الجديد أصغر من أو
# يساوي تقريباً (مع هامش صغير) النطاق السابق — لا توسّع.
TRIANGLE_CONTRACTION_TOLERANCE = 1.05  # هامش 5% يسمح بتفاوت طفيف
TRIANGLE_MIN_CONTRACTION = 0.40  # الحد الأدنى لنسبة الانكماش (لا أقل من 40% من السابق، لتجنب نقاط متطابقة تماماً تُحسب خطأً كـ"تضييق")
TRIANGLE_POINTS = 5  # A, B, C, D, E — كل منها نقطة واحدة


def _classify_triangle_type(highs: list, lows: list) -> str | None:
    """
    يحدد نوع المثلث بعد تأكيد الانكماش الأساسي:
    - Symmetrical: القمم تتراجع AND القواعد ترتفع
    - Ascending: القمم مستوية تقريباً AND القواعد ترتفع فقط
    - Descending: القواعد مستوية تقريباً AND القمم تتراجع فقط

    Args:
        highs: قائمة أسعار القمم بالترتيب الزمني (مثلاً [قمة أصلية, B, D])
        lows: قائمة أسعار القواعد بالترتيب الزمني (مثلاً [A, C, E])

    Returns:
        "symmetrical" | "ascending" | "descending" | None (لا يطابق أي نوع)
    """
    if len(highs) < 2 or len(lows) < 2:
        return None

    highs_declining = all(highs[i] >= highs[i + 1] for i in range(len(highs) - 1))
    lows_rising     = all(lows[i] <= lows[i + 1] for i in range(len(lows) - 1))

    # هامش "مستوي تقريباً": التغير بين أول وآخر قيمة أقل من 10% من القيمة الأولى
    def _roughly_flat(seq):
        if len(seq) < 2 or seq[0] == 0:
            return False
        return abs(seq[-1] - seq[0]) / abs(seq[0]) < 0.10

    highs_flat = _roughly_flat(highs)
    lows_flat  = _roughly_flat(lows)

    if highs_declining and lows_rising:
        if highs_flat and not lows_flat:
            return "ascending"
        if lows_flat and not highs_flat:
            return "descending"
        return "symmetrical"

    return None


def detect_triangle(swings: list, correction_start: dict) -> dict:
    """
    يحاول تصنيف التصحيح الجاري كـ Triangle (Symmetrical/Ascending/
    Descending)، بفحص هل أول 5 نقاط بعد correction_start (A-B-C-D-E)
    تشكّل انكماشاً متتالياً صحيحاً في مدى السعر.

    Args:
        swings: التسلسل الكامل لـ swings.
        correction_start: نقطة البداية (نفس correction_start المستخدم
                مع detect_zigzag/detect_flat).

    Returns:
        نفس بنية detect_zigzag/detect_flat تقريباً، لكن current_wave قد
        يكون أي من wave_A..wave_E (تسميات جديدة لم تظهر في ABC/Zigzag/
        Flat، لأن Triangle له 5 موجات لا 3). المستدعي (wave_classifier
        وelliott_wave_engine) يحتاج التعامل مع wave_D/wave_E كحالات
        "جارية" عادية (next_expected يوضح الموجة التالية).
        فشل الفحص الصارم → {"pattern": "unknown", "reason": "..."}
    """
    if not correction_start or not swings:
        return {"pattern": "unknown", "reason": "no_correction_start_or_swings"}

    start_idx = correction_start["index"]

    after = sorted(
        [s for s in swings if s["index"] > start_idx],
        key=lambda s: s["index"],
    )

    points = after[:TRIANGLE_POINTS]
    wave_labels = ["wave_A", "wave_B", "wave_C", "wave_D", "wave_E"]
    next_labels = ["wave_B", "wave_C", "wave_D", "wave_E", "impulse"]

    if len(points) == 0:
        return {"pattern": "unknown", "reason": "no_points_after_correction_start"}

    # نبني تدريجياً، لكن لا نحدد triangle_type (النوع: symmetrical/
    # ascending/descending) بثقة إلا بعد اكتمال جميع 5 النقاط. FIX:
    # سابقاً كان الفحص يحاول تحديد النوع بمجرد توفر زوجين من كل نوع
    # (مثلاً بعد A وB وC فقط)، وهذا يُصدر قراراً مبكراً خاطئاً — مثال
    # فعلي اختبرناه: قاعدتان متباعدتان 7% فقط صودف اعتبارهما "مستويتين
    # تقريباً" (عتبة _roughly_flat=10%) فصُنِّف الشكل "descending" خطأً،
    # بينما هو فعلياً "symmetrical" جزئي لم يكتمل بعد (كلا الطرفين
    # يتحركان، لكن بعدد نقاط غير كافٍ للتمييز الموثوق بين "يتحرك
    # بوضوح" و"مستوٍ تقريباً بالصدفة").
    highs_seq = [p["price"] for p in [correction_start] + points if p["type"] == "HIGH"]
    lows_seq  = [p["price"] for p in [correction_start] + points if p["type"] == "LOW"]

    is_complete = len(points) >= TRIANGLE_POINTS

    if is_complete:
        # فقط الآن (5 نقاط كاملة) نحدد النوع بثقة — لدينا 3 قمم و3
        # قواعد على الأقل (حسب اتجاه correction_start)، كافية لتمييز
        # حقيقي بين "متحرك بوضوح" و"مستوٍ تقريباً".
        triangle_type = _classify_triangle_type(highs_seq, lows_seq)
        if triangle_type is None:
            return {"pattern": "unknown", "reason": "no_contraction_detected"}
    else:
        # حالة جارية: نتحقق فقط من عدم وجود توسّع صريح حتى الآن (دليل
        # سلبي مبكر)، لكن لا نخمّن النوع النهائي قبل اكتمال البيانات.
        if len(highs_seq) >= 2 and highs_seq[-1] > highs_seq[0] * TRIANGLE_CONTRACTION_TOLERANCE:
            return {"pattern": "unknown", "reason": "highs_expanding_not_contracting"}
        if len(lows_seq) >= 2 and lows_seq[-1] < lows_seq[0] / TRIANGLE_CONTRACTION_TOLERANCE:
            return {"pattern": "unknown", "reason": "lows_expanding_not_contracting"}
        triangle_type = None

    current_wave = wave_labels[len(points) - 1]
    next_wave    = next_labels[len(points) - 1]

    if not is_complete:
        return {
            "pattern": "triangle",
            "current_wave": current_wave,
            "next_expected": next_wave,
            "subwave": None,
            "confidence": 60 if triangle_type else 40,
            "triangle_type": triangle_type,
            "points": points,
        }

    return {
        "pattern": "triangle",
        "current_wave": "wave_E",
        "next_expected": "impulse",
        "subwave": "wave_5",  # نفس اصطلاح "الاكتمال" المستخدم في باقي الأنماط
        "confidence": 75,
        "triangle_type": triangle_type,
        "points": points,
    }


# ---------------------------------------------------------------------------
# الخطوة الخامسة والأخيرة من المشروع: W-X-Y (يبدأ بـ Zigzag-X-Zigzag فقط)
# ---------------------------------------------------------------------------
"""
الفرق الجوهري عن Zigzag/Flat/Triangle: W-X-Y ليس نمطاً تصحيحياً مستقلاً،
بل تركيبة من نمطين تصحيحيين كاملين (W وY) مربوطين بموجة X تصحيحية بسيطة.
كل من W وY هو نمط كامل بحد ذاته (يُكتشف عبر detect_zigzag نفسها).

نبدأ بأبسط وأشيع تركيبة: Zigzag-X-Zigzag (Double Zigzag). التوسعة
لاحقاً لدعم Flat كـW أو Y تكون مجرد استبدال استدعاء detect_zigzag
بقائمة دوال تُجرَّب بالتتابع (نفس استدعاءات detect_zigzag/detect_flat
الموجودة فعلاً) — لا إعادة بناء.

بنية Double Zigzag المتوقعة (assuming correction_start = HIGH):
    W: Zigzag كامل (5-3-5) ينتهي بـ wave_C
    X: نقطة تصحيحية واحدة ترتد جزئياً من نهاية W (شبيهة بموجة B)
    Y: Zigzag كامل آخر (5-3-5) بنفس الاتجاه العام لـW

X لا تتجاوز عادة 100% من طول W (وإلا أصبح الشكل تصحيحاً مختلفاً
بالكامل)، ولا تكون صغيرة جداً (وإلا لم تكن X حقيقية بل ضوضاء).
"""

WXY_X_MIN_RATIO = 0.20  # X لا تقل عن 20% من طول W (تجنب ضوضاء تافهة)
WXY_X_MAX_RATIO = 0.85  # X لا تتجاوز 85% من طول W (وإلا أصبح تصحيحاً مختلفاً)


def _wave_range(points: list) -> float:
    """يحسب طول الموجة (الفرق بين أعلى وأدنى سعر ضمن نقاطها)."""
    if not points:
        return 0.0
    prices = [p["price"] for p in points]
    return abs(max(prices) - min(prices))


def detect_wxy(swings: list, correction_start: dict) -> dict:
    """
    يحاول تصنيف التصحيح الجاري كـ Double Zigzag (W-X-Y)، بفحص هل
    التصحيح يبدأ بـ Zigzag كامل (W)، يتبعه ارتداد جزئي (X)، ثم Zigzag
    كامل آخر بنفس الاتجاه العام (Y).

    Args:
        swings: التسلسل الكامل لـ swings.
        correction_start: نقطة البداية، نفس المستخدم مع باقي الكاشفات.

    Returns:
        نفس بنية detect_zigzag/detect_flat/detect_triangle تقريباً
        (pattern="wxy")، مع current_wave من "wave_W"/"wave_X"/"wave_Y"
        (تسميات جديدة بالكامل، خاصة بهذا التركيب فقط).
        فشل الفحص الصارم في أي مرحلة → {"pattern": "unknown", "reason": "..."}
    """
    if not correction_start or not swings:
        return {"pattern": "unknown", "reason": "no_correction_start_or_swings"}

    # ── المرحلة 1: محاولة بناء W كـ Zigzag كامل ──────────────────────
    w_result = detect_zigzag(swings, correction_start)

    if w_result.get("pattern") != "zigzag":
        return {"pattern": "unknown", "reason": "wave_w_not_zigzag"}

    if w_result.get("current_wave") != "wave_C" or w_result.get("subwave") != "wave_5":
        # W لم يكتمل بعد (لا يزال جارياً) — هذا تصحيح جارٍ، ليس فشلاً،
        # لكن لا يمكن الحكم بـ W-X-Y بثقة قبل اكتمال W نفسه بالكامل.
        return {
            "pattern": "wxy",
            "current_wave": "wave_W",
            "next_expected": "wave_W_completion",
            "subwave": None,
            "confidence": w_result.get("confidence", 0),
            "w_detail": w_result,
        }

    wave_c_points = w_result.get("wave_c_points")
    if not wave_c_points:
        return {"pattern": "unknown", "reason": "wave_w_missing_c_points"}

    w_end = wave_c_points[-1]
    w_length = _wave_range(w_result.get("wave_a_points", []) + wave_c_points)

    if w_length == 0:
        return {"pattern": "unknown", "reason": "zero_length_wave_w"}

    # ── المرحلة 2: البحث عن X (نقطة تصحيحية واحدة بعد نهاية W) ───────
    # نفس نوع correction_start (تماماً كموجة B في detect_zigzag/detect_flat)
    x_end_type = correction_start["type"]
    x_end = _find_swing_after(swings, w_end["index"], x_end_type)

    if not x_end:
        return {
            "pattern": "wxy",
            "current_wave": "wave_W",
            "next_expected": "wave_X",
            "subwave": "wave_5",  # W نفسها مكتملة، لكن X لم تبدأ بعد
            "confidence": w_result.get("confidence", 0),
            "w_detail": w_result,
        }

    x_length = abs(x_end["price"] - w_end["price"])
    x_ratio = x_length / w_length

    if not (WXY_X_MIN_RATIO <= x_ratio <= WXY_X_MAX_RATIO):
        return {
            "pattern": "unknown",
            "reason": "wave_x_ratio_invalid",
            "x_ratio": round(x_ratio, 4),
        }

    # ── المرحلة 3: محاولة بناء Y كـ Zigzag كامل آخر بعد X ─────────────
    y_result = detect_zigzag(swings, x_end)

    if y_result.get("pattern") != "zigzag":
        return {
            "pattern": "wxy",
            "current_wave": "wave_X",
            "next_expected": "wave_Y",
            "subwave": None,
            "confidence": w_result.get("confidence", 0),
            "w_detail": w_result,
            "x_ratio": round(x_ratio, 4),
        }

    y_current = y_result.get("current_wave")
    y_subwave = y_result.get("subwave")

    if y_current != "wave_C" or y_subwave != "wave_5":
        # Y جارية لكن لم تكتمل بعد — حالة تقدّم طبيعية، لا فشل.
        # FIX (تبسيط التسمية): نبقي current_wave="wave_X" (لا تسمية
        # مركّبة مثل "wave_Y_wave_A") لتفادي قيمة غير متوقعة في بقية
        # النظام (recommendation_builder وغيرها تتوقع wave_A/B/C/D/E
        # فقط). تفاصيل تقدّم Y الداخلية متاحة في y_detail لمن يحتاجها.
        return {
            "pattern": "wxy",
            "current_wave": "wave_X",
            "next_expected": "wave_Y",
            "subwave": None,
            "confidence": int((w_result.get("confidence", 0) + y_result.get("confidence", 0)) / 2),
            "w_detail": w_result,
            "y_detail": y_result,
            "x_ratio": round(x_ratio, 4),
        }

    confidence = int((w_result.get("confidence", 0) + y_result.get("confidence", 0)) / 2)

    return {
        "pattern": "wxy",
        "current_wave": "wave_Y",
        "next_expected": "impulse",
        "subwave": "wave_5",  # نفس اصطلاح "الاكتمال الكامل" المستخدم في باقي الأنماط
        "confidence": confidence,
        "w_detail": w_result,
        "y_detail": y_result,
        "x_ratio": round(x_ratio, 4),
    }