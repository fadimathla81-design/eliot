# wave_engine/correction_state.py
"""
مصدر الحقيقة الوحيد (Single Source of Truth) لتحديد هل التصحيح ABC
اكتمل فعلياً على أي تايم فريم.

المشكلة التي يحلها هذا الملف:
كانت أماكن متعددة في النظام (recommendation_builder, trade_setup_builder,
wave_alignment, AI context, Telegram, ...) تفحص "هل التصحيح اكتمل؟" كل
واحدة بمعيارها الخاص (بعضها يعتمد على next_expected=="trend_resumption"،
بعضها على current_wave=="wave_C" فقط بدون فحص phase، إلخ). هذا أدى لتناقضات
فعلية مثل ظهور w1_correction_completed=True بينما current_wave=="wave_A"
و phase=="correction_ongoing" — تناقض منطقي صريح.

القاعدة الصارمة الوحيدة المعتمدة الآن في كل النظام:
    التصحيح ABC يُعتبر مكتملاً فقط إذا:
        current_wave == "wave_C"  AND  phase == "correction_completed"

كل جزء من النظام يحتاج معرفة حالة التصحيح يجب أن يستخدم get_correction_state
بدل إعادة كتابة هذا الشرط بمعيار مختلف.
"""


def get_correction_state(tf_data: dict) -> dict:
    """
    يبني حالة موحدة لاكتمال التصحيح من بيانات تايم فريم واحد
    (عنصر من wave_map، مثل wave_map["W1"]).

    Args:
        tf_data: قاموس يحتوي على "elliott" و (اختياري) "context"،
                 بنفس البنية الموجودة في wave_map[tf].

    Returns:
        قاموس بحالة موحدة:
        {
            "completed": bool,       # القاعدة الصارمة الوحيدة
            "current_wave": str,
            "phase": str,
            "next_expected": str,
            "confidence": int/float,
            "pattern": str,
            "cycle": "trend" | "correction",
        }
    """
    elliott = tf_data.get("elliott", {}) if tf_data else {}
    context = tf_data.get("context", {}) if tf_data else {}

    current_wave = elliott.get("current_wave")
    phase        = elliott.get("phase")
    next_wave    = elliott.get("next_wave")
    pattern      = elliott.get("pattern")

    # FIX: القاعدة الصارمة كانت مكتوبة لـ ABC/Zigzag/Flat فقط (تنتهي
    # دائماً عند wave_C)، لكن Triangle ينتهي عند wave_E (5 موجات A-E
    # لا 3)، وWXY ينتهي عند wave_Y (تركيبة W-X-Y). لو تُرك الشرط مقيداً
    # بنمط واحد فقط، أي نمط معقد مكتمل فعلياً كان سيُحسب خطأً
    # completed=False — تناقض منطقي صريح من نفس العائلة التي أصلحناها
    # سابقاً لـ W1/D1. الآن: خريطة عامة تغطي كل الأنماط المدعومة حالياً
    # ومستقبلاً (إضافة نمط جديد = سطر واحد هنا، لا إعادة هيكلة).
    terminal_wave_map = {
        "triangle": "wave_E",
        "wxy": "wave_Y",
    }
    terminal_wave = terminal_wave_map.get(pattern, "wave_C")

    # القاعدة الصارمة الوحيدة — لا توجد طريقة أخرى معتمدة لاعتبار
    # التصحيح مكتملاً في أي مكان من النظام.
    completed = (
        current_wave == terminal_wave
        and phase == "correction_completed"
    )

    return {
        "completed": completed,
        "current_wave": current_wave,
        "phase": phase,
        "next_expected": (
            "trend_resumption" if completed else next_wave
        ),
        "confidence": (
            elliott.get("confidence")
            if elliott.get("confidence") is not None
            else context.get("confidence", 0)
        ),
        "pattern": elliott.get("pattern"),
        "cycle": "trend" if completed else "correction",
    }


def attach_correction_states(wave_map: dict) -> dict:
    """
    يضيف correction_state لكل تايم فريم داخل wave_map، في مكان واحد
    مركزي بعد بناء wave_map مباشرة (في market_analyzer.py).

    لا يُعدّل wave_map في مكانه (immutable-friendly)؛ يرجع نفس
    الكائن بعد التعديل للوضوح في نقطة الاستدعاء.
    """
    for tf in ("W1", "D1", "H4", "H1"):
        if tf in wave_map:
            wave_map[tf]["correction_state"] = get_correction_state(wave_map[tf])
    return wave_map