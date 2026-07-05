# telegram_bot/telegram_formatter.py
"""
مسؤول عن بناء رسائل تليجرام المقروءة والمفيدة من بيانات result الخام.

المبدأ الأساسي: الرسالة يجب تجيب على 3 أسئلة عملية:
1. ما هو الوضع الحالي؟ (الاتجاه والنمط)
2. هل يمكن الدخول الآن أم لا، ولماذا؟
3. لو دخلت، أين الأهداف والستوبات؟
"""

import os
from telegram import Bot
from telegram.constants import ParseMode


# ── رموز بصرية موحّدة ────────────────────────────────────
EMOJI = {
    "buy"    : "📈",
    "sell"   : "📉",
    "wait"   : "⏳",
    "warn"   : "⚠️",
    "ok"     : "✅",
    "target" : "🎯",
    "stop"   : "🛑",
    "info"   : "ℹ️",
    "pattern": "🌊",
    "clock"  : "🕐",
    "fire"   : "🔥",
    "shield" : "🛡️",
    "arrow"  : "➡️",
}

# تسميات الأنماط بالعربي
PATTERN_NAMES = {
    "zigzag"         : "زيجزاج (5-3-5)",
    "flat"           : "فلات (3-3-5)",
    "triangle"       : "مثلث (3-3-3-3-3)",
    "wxy"            : "مزدوج زيجزاج (W-X-Y)",
    "ABC"            : "ABC تصحيحي",
    "bullish_impulse": "دفعي صاعد",
    "bearish_impulse": "دفعي هابط",
    "unknown"        : "غير محدد",
}

# تسميات الإشارات بالعربي
SIGNAL_LABELS = {
    "BUY_NOW"                       : "🔥 شراء فوري",
    "STRONG_BUY"                    : "🔥 شراء قوي",
    "BUY_NOW_EARLY"                 : "⚡ شراء مبكر",
    "STRONG_BUY_EARLY"              : "⚡ شراء مبكر قوي",
    "SELL_NOW"                      : "🔥 بيع فوري",
    "STRONG_SELL"                   : "🔥 بيع قوي",
    "SELL_NOW_EARLY"                : "⚡ بيع مبكر",
    "STRONG_SELL_EARLY"             : "⚡ بيع مبكر قوي",
    "WAIT_BUY"                      : "⏳ انتظر — شراء لاحق",
    "WAIT_SELL"                     : "⏳ انتظر — بيع لاحق",
    "WAIT_REVERSAL_CONFIRMATION_BUY": "⏳ انتظر تأكيد انعكاس صاعد",
    "WAIT_REVERSAL_CONFIRMATION_SELL":"⏳ انتظر تأكيد انعكاس هابط",
    "NO_TRADE"                      : "🚫 لا صفقة الآن",
}

WAVE_NAMES = {
    "wave_A": "A", "wave_B": "B", "wave_C": "C",
    "wave_D": "D", "wave_E": "E",
    "wave_W": "W", "wave_X": "X", "wave_Y": "Y",
    "wave_1": "1", "wave_2": "2", "wave_3": "3",
    "wave_4": "4", "wave_5": "5",
    "trend_resumption": "استئناف الاتجاه",
    "impulse"         : "دفع جديد",
    "unknown"         : "غير محدد",
}

IMMEDIATE_SIGNALS = {
    "BUY_NOW", "STRONG_BUY", "BUY_NOW_EARLY", "STRONG_BUY_EARLY",
    "SELL_NOW", "STRONG_SELL", "SELL_NOW_EARLY", "STRONG_SELL_EARLY",
}


def _fmt_price(price, decimals=2):
    if price is None:
        return "—"
    return f"{price:,.{decimals}f}"


def _fmt_wave(wave_key):
    return WAVE_NAMES.get(wave_key, wave_key or "—")


def _fmt_pattern(pattern_key):
    return PATTERN_NAMES.get(pattern_key, pattern_key or "—")


def _get_wait_reason(recommendation, trade_setup):
    """
    يستخرج السبب الحقيقي الواضح للانتظار من بيانات recommendation,
    ليُعرض للمستخدم كجواب مباشر على "لماذا لا ندخل الآن؟"
    """
    signal  = recommendation.get("signal", "")
    reasons = recommendation.get("reasons", [])
    h4_role = recommendation.get("h4_role", "")

    # البحث في reasons عن السبب الأوضح
    for r in reasons:
        if "التصحيح الأسبوعي" in r or "W1" in r:
            return "W1 في تصحيح لم يكتمل بعد"
        if "التصحيح اليومي" in r or "D1 لم يكتمل" in r:
            return "D1 في تصحيح لم يكتمل بعد"
        if "H4 يعارض" in r:
            return "H4 يعارض الاتجاه هيكلياً"
        if "BOS على H4/H1 غير مؤكد" in r:
            return "BOS على H4/H1 لم يتأكد بعد"
        if "H1 BOS فعلي" in r and "يعارض" in r:
            return "H1 BOS يعارض الاتجاه"

    if h4_role == "none":
        return "H4 يعارض الاتجاه"

    if "WAIT_REVERSAL" in signal:
        return "ننتظر تأكيد انعكاس (BOS صاعد على H4+H1)"

    return "الشروط لم تكتمل بعد"


def _get_what_we_need(signal):
    """
    ماذا نحتاج لنرى لنتحرك؟ جواب واضح ومحدد.
    """
    if "BUY" in signal:
        return "كسر هيكلي صاعد (BOS Bullish) على H4 وH1 مع اكتمال D1"
    if "SELL" in signal:
        return "كسر هيكلي هابط (BOS Bearish) على H4 وH1 مع اكتمال D1"
    return "انتظر وضوح الاتجاه"


def _build_wave_context_section(wave_map):
    """
    يبني قسم السياق الموجي بشكل موجز ومقروء.
    """
    lines = []
    for tf in ["W1", "D1", "H4", "H1"]:
        data = wave_map.get(tf, {})
        elliott = data.get("elliott", {})
        pattern = _fmt_pattern(elliott.get("pattern"))
        wave    = _fmt_wave(elliott.get("current_wave"))
        conf    = elliott.get("confidence", 0)
        lines.append(f"  {tf}: {pattern} | موجة {wave} | ثقة {conf}%")
    return "\n".join(lines)


def _build_entry_section(trade_setup, direction):
    """
    يبني قسم نقطة الدخول والأهداف والستوبات بوضوح.
    """
    entry_zone  = trade_setup.get("entry_zone", [])
    targets     = trade_setup.get("targets", [])
    trade_stop  = trade_setup.get("trade_stop")
    structural  = trade_setup.get("structural_stop")
    catastro    = trade_setup.get("catastrophic_stop")
    entry_status= trade_setup.get("entry_status", "")

    lines = []

    # ── منطقة الدخول ─────────────────────────
    if entry_zone and len(entry_zone) == 2:
        low  = _fmt_price(min(entry_zone))
        high = _fmt_price(max(entry_zone))
        lines.append(f"📍 *منطقة الدخول:* {low} — {high}")
    if entry_status:
        lines.append(f"   {entry_status}")

    lines.append("")

    # ── الأهداف ──────────────────────────────
    if targets:
        lines.append(f"{EMOJI['target']} *الأهداف:*")
        for i, t in enumerate(targets, 1):
            label = ["قريب", "متوسط", "بعيد", "نهائي"][min(i-1, 3)]
            lines.append(f"   TP{i} ({label}): {_fmt_price(t)}")
    else:
        lines.append(f"{EMOJI['target']} *الأهداف:* لم تُحدَّد بعد")

    lines.append("")

    # ── مستويات الستوب بأدوارها ──────────────
    lines.append(f"{EMOJI['stop']} *مستويات الوقف:*")

    if trade_stop is not None:
        lines.append(f"   🔴 تكتيكي (أغلق الصفقة هنا): {_fmt_price(trade_stop)}")

    # نعرض الهيكلي فقط لو مختلف عن التكتيكي وليس بعيداً جداً
    if structural is not None and trade_stop is not None:
        diff_pct = abs(structural - trade_stop) / trade_stop * 100
        if diff_pct < 30 and structural != trade_stop:
            lines.append(f"   🟠 هيكلي (السيناريو يضعف): {_fmt_price(structural)}")
        elif diff_pct >= 30:
            # بعيد جداً — نوضح دوره بدل الرقم المربك
            lines.append(f"   🟡 بنيوي (إلغاء السيناريو الكامل): {_fmt_price(catastro or structural)}")

    return "\n".join(lines)


def build_signal_message(symbol, result, gemini_text=None):
    """
    يبني رسالة تليجرام كاملة ومفهومة من result الخام.

    البنية:
    1. العنوان (الإشارة + الرمز + الاتجاه)
    2. السبب (لو WAIT: لماذا؟ ماذا ننتظر؟)
    3. السياق الموجي (4 فريمات موجزة)
    4. خطة التداول (دخول، أهداف، ستوبات)
    5. الثقة والإيجاز
    6. تحليل Gemini/Groq (اختياري)
    """
    recommendation = result.get("recommendation", {})
    trade_setup    = result.get("trade_setup", {})
    wave_map       = result.get("wave_map", {})

    signal     = recommendation.get("signal", "WAIT")
    direction  = recommendation.get("direction", "neutral")
    confidence = recommendation.get("confidence", 0)
    score      = recommendation.get("score", 0)

    signal_label = SIGNAL_LABELS.get(signal, signal)
    dir_emoji    = EMOJI["buy"] if direction == "buy" else (
                   EMOJI["sell"] if direction == "sell" else EMOJI["info"])

    is_immediate = signal in IMMEDIATE_SIGNALS
    is_wait      = not is_immediate and signal != "NO_TRADE"
    is_no_trade  = signal == "NO_TRADE"

    lines = []

    # ════════════════════════════════════════
    # 1. العنوان
    # ════════════════════════════════════════
    lines.append(f"{dir_emoji} *{signal_label}*")
    lines.append(f"*{symbol}*  |  ثقة: {confidence}%  |  نقاط: {score}/100")
    lines.append("━━━━━━━━━━━━━━━━━━━━")

    # ════════════════════════════════════════
    # 2. السبب (أهم جزء لحالة WAIT)
    # ════════════════════════════════════════
    if is_wait:
        wait_reason = _get_wait_reason(recommendation, trade_setup)
        what_needed = _get_what_we_need(signal)
        lines.append(f"{EMOJI['clock']} *لماذا ننتظر؟*")
        lines.append(f"   {wait_reason}")
        lines.append(f"{EMOJI['arrow']} *ماذا نحتاج؟*")
        lines.append(f"   {what_needed}")
        lines.append("━━━━━━━━━━━━━━━━━━━━")

    elif is_no_trade:
        context = recommendation.get("context", "تعارض في الاتجاه")
        lines.append(f"{EMOJI['warn']} *السبب:* {context}")
        lines.append("━━━━━━━━━━━━━━━━━━━━")

    elif is_immediate:
        entry_status = trade_setup.get("entry_status", "")
        if entry_status:
            lines.append(f"{EMOJI['fire']} {entry_status}")
            lines.append("━━━━━━━━━━━━━━━━━━━━")

    # ════════════════════════════════════════
    # 3. السياق الموجي
    # ════════════════════════════════════════
    if wave_map:
        lines.append(f"{EMOJI['pattern']} *السياق الموجي:*")
        lines.append(_build_wave_context_section(wave_map))
        lines.append("━━━━━━━━━━━━━━━━━━━━")

    # ════════════════════════════════════════
    # 4. خطة التداول (فقط لو في اتجاه واضح)
    # ════════════════════════════════════════
    if direction in ("buy", "sell") and trade_setup:
        lines.append(f"{EMOJI['shield']} *خطة التداول:*")
        lines.append(_build_entry_section(trade_setup, direction))
        lines.append("━━━━━━━━━━━━━━━━━━━━")

    # ════════════════════════════════════════
    # 5. السعر الحالي + الإشارة الموجزة
    # ════════════════════════════════════════
    current_price = result.get("current_price") or trade_setup.get("current_price")
    if current_price:
        lines.append(f"{EMOJI['info']} *السعر الحالي:* {_fmt_price(current_price)}")

    # ════════════════════════════════════════
    # 6. تحليل Gemini/Groq (موجز، اختياري)
    # ════════════════════════════════════════
    if gemini_text and len(gemini_text.strip()) > 10:
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"{EMOJI['info']} *تحليل AI (ملخص):*")
        # نأخذ أول 400 حرف فقط لتجنب رسائل طويلة جداً
        summary = gemini_text.strip()[:400]
        if len(gemini_text.strip()) > 400:
            summary += "..."
        lines.append(summary)

    return "\n".join(lines)


async def send_signal(symbol, result, gemini_text=None):
    """
    يرسل رسالة التليجرام المنسّقة.
    """
    token   = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("⚠️ TELEGRAM_BOT_TOKEN أو TELEGRAM_CHAT_ID غير موجودان في البيئة")
        return False

    try:
        bot     = Bot(token=token)
        message = build_signal_message(symbol, result, gemini_text)

        await bot.send_message(
            chat_id    = chat_id,
            text       = message,
            parse_mode = ParseMode.MARKDOWN,
        )
        print(f"✅ تم إرسال رسالة تليجرام بنجاح")
        return True

    except Exception as e:
        print(f"❌ خطأ في إرسال رسالة تليجرام: {e}")
        return False


def send_signal_sync(symbol, result, gemini_text=None):
    """
    Wrapper متزامن (sync) لـ send_signal — يُستخدم من main.py الذي
    يعمل بدون async/await. يتولى إنشاء event loop تلقائياً وتشغيل
    الدالة async بداخله بشكل آمن.

    الاستخدام في main.py:
        from telegram_bot.telegram_formatter import send_signal_sync
        sent = send_signal_sync(SYMBOL, result, gemini_text=ai_text)
    """
    import asyncio
    try:
        # لو يوجد event loop جارٍ (مثلاً في Jupyter أو بعض بيئات async)
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # نستخدم run_coroutine_threadsafe لو الـ loop جارٍ فعلاً
            import concurrent.futures
            future = asyncio.run_coroutine_threadsafe(
                send_signal(symbol, result, gemini_text), loop
            )
            return future.result(timeout=30)
        else:
            return loop.run_until_complete(
                send_signal(symbol, result, gemini_text)
            )
    except RuntimeError:
        # لا يوجد event loop — ننشئ واحداً جديداً
        return asyncio.run(send_signal(symbol, result, gemini_text))