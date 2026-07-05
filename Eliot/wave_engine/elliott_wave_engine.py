# wave_engine/elliott_wave_engine.py
"""
Elliott Wave Pattern Detection with Phase System.

CHANGE LOG (this revision):
- detect_elliott_pattern now accepts `parent_direction` and forwards it
  to classify_wave (the actual source of truth for the opposite-direction
  check), instead of relying on string-matching parent_pattern.
- The "is this impulse actually opposite to the parent" check is folded
  directly into the impulse branch (no more dead code after an early
  return).
- correction_start (now produced by classify_wave when pattern == "ABC")
  is forwarded into detect_correction instead of being re-derived.
- منع التناقض بين Pattern و Wave (bullish_impulse + wave_C → ABC)
- ✅ استيراد detect_wave_stage من wave_stage_detector (حذف الـ stub)

NEW (هذه النسخة — مشروع الأنماط المعقدة، الخطوة الثانية):
- إضافة فرع معزول جديد لـ pattern == "zigzag" (الناتج من classify_wave
  بعد ترقية ABC إلى Zigzag عبر complex_correction_detector.detect_zigzag).
  سابقاً كان هذا الفرع يُتجاهَل بالكامل: الكود يتخطى _build_impulse_result
  (لأن "zigzag" ليست "bullish_impulse"/"bearish_impulse")، ثم يستدعي
  detect_correction بغض النظر عن قيمة pattern، فيُعاد التصنيف من جديد
  بمحرك أضعف (نقاط A/B/C مفردة بلا فحص بنية داخلية) يُخرج دائماً "ABC" —
  وبهذا "تضيع" نتيجة Zigzag الأكثر دقة والمفحوصة بنيوياً بالكامل.
  الآن: عند pattern == "zigzag"، نبني النتيجة مباشرة من تفاصيل
  zigzag_detail (المرفقة من classify_wave) بدل استدعاء detect_correction
  من جديد — لأن detect_zigzag فحص فعلياً 5 نقاط دفعية لكل من A و C
  (فحص أكثر تشدداً وموثوقية من نقطة A/B/C مفردة).
"""

from wave_engine.wave_classifier import classify_wave
from wave_engine.correction_detector import detect_correction
from wave_engine.wave_stage_detector import detect_wave_stage


def _build_impulse_result(pattern, sequence, classification):
    stage = detect_wave_stage(sequence)
    current_wave = stage["current_wave"]
    next_wave = stage["next_wave"]
    
    # منع التناقض: إذا كان pattern impulse لكن أنت في ABC
    # غيّر pattern إلى ABC وسيأتي phase صحيح من detect_correction
    if (
        pattern in ("bullish_impulse", "bearish_impulse")
        and
        current_wave in ("wave_A", "wave_B", "wave_C")
    ):
        pattern = "ABC"
    
    phase = "impulse_completed" if current_wave == "wave_5" else "impulse_ongoing"
    return {
        "pattern": pattern,
        "current_wave": current_wave,
        "next_wave": next_wave,
        "phase": phase,
        "subwave": None,
        "confidence": int((classification["confidence"] + stage["confidence"]) / 2),
    }


def _build_complex_pattern_result(classification):
    """
    NEW: يبني نتيجة Elliott مباشرة من تفاصيل النمط المعقد المرفقة في
    classification (zigzag_detail، من complex_correction_detector عبر
    wave_classifier._try_upgrade_to_zigzag). يدعم zigzag/flat/triangle/
    wxy بنفس الدالة لأن بنية المخرجات متطابقة بين الكاشفين
    (current_wave, next_expected, subwave, confidence) — فقط pattern
    والموجة الأخيرة المتوقعة (terminal wave) تختلفان.

    لا يستدعي detect_correction — نتيجة النمط المعقد المفحوصة بنيوياً
    أكثر موثوقية من محرك ABC البسيط.

    إذا لم تتوفر zigzag_detail لأي سبب (دفاعي، لا يجب أن يحدث طالما
    pattern in ("zigzag", "flat", "triangle", "wxy") قادمة من
    classify_wave)، نتراجع بأمان لإرجاع None، والمستدعي
    (detect_elliott_pattern) يسقط إلى المسار العادي عبر
    detect_correction كما كان يحدث سابقاً.
    """
    detail = classification.get("zigzag_detail")
    if not detail:
        return None

    pattern      = detail.get("pattern", classification.get("pattern"))
    current_wave = detail.get("current_wave")
    subwave      = detail.get("subwave")
    next_wave    = detail.get("next_expected")
    confidence   = detail.get("confidence", classification.get("confidence", 0))

    # FIX: الموجة الأخيرة المتوقعة تختلف حسب النمط — wave_C لـ
    # zigzag/flat، wave_E لـ triangle، wave_Y لـ wxy. سابقاً كان
    # الشرط يفحص "wave_C" فقط، فكان Triangle/WXY المكتملان فعلياً
    # سيُحسبان خطأً phase="correction_ongoing" (نفس فئة الباق التي
    # أُصلحت في correction_state.py لنفس السبب بالضبط).
    terminal_wave_map = {
        "zigzag": "wave_C", "flat": "wave_C",
        "triangle": "wave_E", "wxy": "wave_Y",
    }
    terminal_wave = terminal_wave_map.get(pattern, "wave_C")

    phase = (
        "correction_completed"
        if (current_wave == terminal_wave and subwave == "wave_5")
        else "correction_ongoing"
    )

    return {
        "pattern": pattern,
        "current_wave": current_wave,
        "next_wave": next_wave,
        "phase": phase,
        "subwave": subwave,
        "confidence": confidence,
    }


def _build_correction_result(correction):
    if not correction or correction.get("correction_type") in (None, "unknown"):
        return None
    current_wave = correction["current_wave"]
    subwave = correction.get("subwave")
    next_wave = correction["next_expected"]
    phase = (
        "correction_completed"
        if (current_wave == "wave_C" and subwave == "wave_5")
        else "correction_ongoing"
    )
    return {
        "pattern": correction["correction_type"],
        "current_wave": current_wave,
        "next_wave": next_wave,
        "phase": phase,
        "subwave": subwave,
        "confidence": correction["confidence"],
    }


def detect_elliott_pattern(sequence, parent_pattern=None, parent_direction=None):
    """
    كشف نمط إليوت مع الحماية من التناقضات
    
    ✅ يستخدم detect_wave_stage من wave_stage_detector.py (لا stub)
    """
    classification = classify_wave(
    sequence,
    parent_pattern=parent_pattern,
    parent_direction=parent_direction
    )

    print("\nCLASSIFICATION DEBUG")
    print(classification)

    pattern = classification["pattern"]

    if pattern in ("bullish_impulse", "bearish_impulse"):
        return _build_impulse_result(
            pattern,
            sequence,
            classification
        )

    # NEW: فرع معزول للأنماط المعقدة (Zigzag أو Flat) — يُستخدم فقط إذا
    # classify_wave رقّى التصحيح فعلياً لنمط مفحوص البنية الداخلية. لا
    # يتداخل مع أي مسار آخر (ABC العادي يستمر كما كان تماماً إذا لم
    # يتحقق أي نمط معقد).
    if pattern in ("zigzag", "flat", "triangle", "wxy"):
        complex_result = _build_complex_pattern_result(classification)
        if complex_result is not None:
            print(f"\n{pattern.upper()} RESULT")
            print(complex_result)
            return complex_result
        # دفاعي: zigzag_detail غائبة لأي سبب — نسقط للمسار العادي أدناه

    correction_start = classification.get(
        "correction_start"
    )

    correction = detect_correction(
        sequence,
        parent_pattern=parent_pattern,
        correction_start=correction_start
    )

    print("\nCORRECTION DEBUG")
    print(correction)
    correction_result = _build_correction_result(correction)
    if correction_result is not None:
        return correction_result

    return {
        "pattern": "unknown",
        "current_wave": "unknown",
        "next_wave": "unknown",
        "phase": "unknown",
        "subwave": None,
        "confidence": 0,
    }