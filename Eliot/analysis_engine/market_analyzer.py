# analysis_engine/market_analyzer.py

import MetaTrader5 as mt5
import pandas as pd

from multi_timeframe_engine.timeframe_loader import load_timeframes
from multi_timeframe_engine.timeframe_summary import analyze_all_timeframes
from multi_timeframe_engine.alignment_engine import calculate_alignment
from multi_timeframe_engine.trend_alignment import advanced_alignment
from trend_engine.weekly_trend import analyze_weekly_trend
from fibonacci_engine.fibonacci import analyze_fibonacci
from volume_engine.volume_analyzer import analyze_volume
from wave_engine.pivot_detector import get_last_pivots
from wave_engine.wave_detector import detect_wave_structure
from wave_engine.swing_structure import build_swing_sequence
from wave_engine.wave_confidence import calculate_wave_confidence
from structure_engine.bos_detector import detect_bos
from structure_engine.choch_detector import detect_choch
from recommendation_engine.recommendation_builder import build_recommendation
from structure_engine.timeframe_structure import analyze_structure
from entry_engine.entry_decision import build_entry_decision
from wave_engine.wave_context import build_wave_context
from wave_engine.multi_tf_wave_engine import analyze_multi_tf_waves
from wave_engine.wave_alignment import calculate_wave_alignment
from wave_engine.wave_context_engine import detect_wave_context
from wave_engine.wave_sequencer import build_wave_sequence
from wave_engine.wave_score import calculate_wave_score
from recommendation_engine.trade_setup_builder import build_trade_setup
from wave_engine.elliott_rules_validator import validate_elliott_rules
from recommendation_engine.signal_engine import build_signal
from wave_engine.bias_engine import get_bias_from_elliott, get_next_bias
# FIX (هذا الإصلاح): استيراد المحرك المركزي لحالة اكتمال التصحيح.
# سابقاً كان market_analyzer.py يحاول قراءة wave_map["W1"].get(
# "correction_state") بينما لا يوجد أي استدعاء فعلي لبناء هذا
# المفتاح — فكان يرجع None دائماً، فيسقط build_recommendation على
# الـ fallback المحلي فقط (وكان فيه باق سابق أصلحناه بشكل مستقل).
# الآن نبني correction_state فعلياً داخل wave_map لكل تايم فريم.
from wave_engine.correction_state import attach_correction_states


def calc_atr(df: pd.DataFrame, period: int = 14) -> float | None:
    try:
        if df is None or len(df) < period + 1:
            return None
        required_cols = {"high", "low", "close"}
        if not required_cols.issubset(df.columns):
            return None
        high  = df["high"]
        low   = df["low"]
        close = df["close"]
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low  - close.shift()).abs(),
        ], axis=1).max(axis=1)
        atr_value = tr.rolling(period).mean().iloc[-1]
        if pd.isna(atr_value) or atr_value <= 0:
            return None
        return round(float(atr_value), 5)
    except Exception:
        return None


def get_pip_size(symbol: str) -> float:
    try:
        info = mt5.symbol_info(symbol)
        if info is None:
            return 0.0001
        digits = info.digits
        point  = info.point
        if digits in (3, 5):
            return round(point * 10, 10)
        return point
    except Exception:
        return 0.0001


def get_pip_multiplier(symbol: str) -> float:
    pip_size = get_pip_size(symbol)
    if pip_size <= 0:
        return 10000
    return round(1 / pip_size, 5)


def analyze_market(symbol, candle_limit):

    tick          = mt5.symbol_info_tick(symbol)
    current_price = round(tick.ask, 5) if tick else None

    timeframes = load_timeframes(symbol, candle_limit)
    weekly_df  = timeframes["W1"]

    trend  = analyze_weekly_trend(weekly_df)
    fib    = analyze_fibonacci(weekly_df)
    volume = analyze_volume(weekly_df)
    pivots = get_last_pivots(weekly_df, "W1")
    wave   = detect_wave_structure(pivots)
    swings = build_swing_sequence(pivots)

    wave_sequence = build_wave_sequence(swings)

    print("\nSWINGS")
    print(swings)
    print("\nWAVE SEQUENCE")
    print(wave_sequence)
    print("\nSEQUENCE LENGTH")
    print(len(wave_sequence))

    market_wave_context = detect_wave_context(swings)
    elliott_rules = validate_elliott_rules(wave_sequence)

    summary  = analyze_all_timeframes(timeframes)
    wave_map = analyze_multi_tf_waves(timeframes)

    # FIX (هذا الإصلاح): يبني فعلياً wave_map[tf]["correction_state"]
    # لكل من W1/D1/H4/H1 — المفتاح الذي كان يُقرأ أسفل بدون أن يُبنى
    # أبداً، فيرجع None دائماً ويُسقط build_recommendation على fallback
    # محلي فقط بدل الاعتماد على مصدر الحقيقة الموحد.
    wave_map = attach_correction_states(wave_map)

    print("\n========== MULTI TF DEBUG ==========")
    for tf in ["W1", "D1", "H4", "H1"]:
        print(f"\n{tf}")
        print("pattern:", wave_map[tf]["elliott"]["pattern"])
        print("current:", wave_map[tf]["elliott"]["current_wave"])
        print("direction:", wave_map[tf]["direction"])
        print("swings count:", len(wave_map[tf]["swings"]))
        print("correction_state:", wave_map[tf]["correction_state"])

    w1_elliott = wave_map["W1"]["elliott"]
    d1_elliott = wave_map["D1"]["elliott"]
    h4_elliott = wave_map["H4"]["elliott"]
    h1_elliott = wave_map["H1"]["elliott"]

    wave_context = build_wave_context(w1_elliott)

    weekly_bias = get_bias_from_elliott(w1_elliott, wave_map["W1"].get("direction"))
    daily_bias  = get_bias_from_elliott(d1_elliott, wave_map["D1"].get("direction"))
    h4_bias     = get_bias_from_elliott(h4_elliott, wave_map["H4"].get("direction"))
    h1_bias     = get_bias_from_elliott(h1_elliott, wave_map["H1"].get("direction"))

    weekly_next_bias = get_next_bias(w1_elliott, wave_map["W1"].get("direction"))
    daily_next_bias  = get_next_bias(d1_elliott, wave_map["D1"].get("direction"))
    h4_next_bias     = get_next_bias(h4_elliott, wave_map["H4"].get("direction"))
    h1_next_bias     = get_next_bias(h1_elliott, wave_map["H1"].get("direction"))

    print("\nW1 DEBUG")
    print(w1_elliott)
    print("bias =", weekly_bias)
    print("\nD1 DEBUG")
    print(d1_elliott)
    print("bias =", daily_bias)
    print("\nH4 DEBUG")
    print(h4_elliott)
    print("bias =", h4_bias)
    print("\nH1 DEBUG")
    print(h1_elliott)
    print("bias =", h1_bias)

    wave_alignment = calculate_wave_alignment(wave_map)
    wave_score = calculate_wave_score(w1_elliott, wave_context, wave_alignment)

    weekly_structure = analyze_structure(weekly_df)
    daily_structure  = analyze_structure(timeframes["D1"])
    h4_structure     = analyze_structure(timeframes["H4"])
    h1_structure     = analyze_structure(timeframes["H1"])

    entry = build_entry_decision({
        "W1": weekly_structure,
        "D1": daily_structure,
        "H4": h4_structure,
        "H1": h1_structure
    })

    alignment = calculate_alignment(summary)
    advanced  = advanced_alignment(summary)

    confidence = calculate_wave_confidence(
        w1_elliott,
        fib,
        volume,
        wave_alignment  = wave_alignment,
        trend_alignment = advanced,
        elliott_rules   = elliott_rules,
    )

    weekly_pattern = wave_map["W1"]["elliott"]["pattern"]
    daily_pattern  = wave_map["D1"]["elliott"]["pattern"]
    h4_pattern     = wave_map["H4"]["elliott"]["pattern"]
    h1_pattern     = wave_map["H1"]["elliott"]["pattern"]

    print("\nBIASES")
    print("W1:", weekly_bias)
    print("D1:", daily_bias)
    print("H4:", h4_bias)
    print("H1:", h1_bias)
    print("\nPATTERNS")
    print("W1:", weekly_pattern)
    print("D1:", daily_pattern)
    print("H4:", h4_pattern)
    print("H1:", h1_pattern)

    # ── BOS الرئيسي (W1 + تأكيد H1) ──────────────────────────
    bos = detect_bos(
        swings,
        current_price = current_price,
        h1_swings     = wave_map["H1"]["swings"],
    )

    # BOS منفصل لـ H4 (للتأكيد الهيكلي)
    h4_bos = detect_bos(
        wave_map["H4"]["swings"],
        current_price = current_price,
    )

    # BOS منفصل لـ H1 (للتأكيد الزخمي)
    h1_bos = detect_bos(
        wave_map["H1"]["swings"],
        current_price = current_price,
    )

    choch = detect_choch(summary)

    if not elliott_rules["valid"]:
        return {
            "entry"              : {},
            "signal"             : "NO_TRADE",
            "elliott_rules"      : elliott_rules,
            "trend"              : trend,
            "trade_setup"        : {},
            "fib"                : fib,
            "volume"             : volume,
            "pivots"             : pivots,
            "wave"               : wave,
            "swings"             : swings,
            "wave_sequence"      : wave_sequence,
            "elliott"            : w1_elliott,
            "confidence"         : 0,
            "wave_score"         : 0,
            "wave_context"       : wave_context,
            "market_wave_context": market_wave_context,
            "wave_map"           : wave_map,
            "wave_alignment"     : wave_alignment,
            "timeframes"         : summary,
            "alignment"          : alignment,
            "advanced_alignment" : advanced,
            "bos"                : {},
            "h4_bos"             : {},
            "h1_bos"             : {},
            "choch"              : {},
            "recommendation"     : {
                "signal"    : "NO_TRADE",
                "direction" : "none",
                "score"     : 0,
                "confidence": 0,
                "reasons"   : ["invalid_elliott_structure"]
            },
            "current_price"      : current_price,
            "timeframe_structure": {
                "W1": weekly_structure,
                "D1": daily_structure,
                "H4": h4_structure,
                "H1": h1_structure
            }
        }

    from recommendation_engine.conflict_resolver import (
        resolve_timeframe_conflict,
        get_entry_signal,
    )

    conflict_result = resolve_timeframe_conflict(
        w1_elliott,
        d1_elliott,
        h1_elliott,
        h4_elliott   = h4_elliott,
        w1_direction = wave_map["W1"].get("direction"),
        d1_direction = wave_map["D1"].get("direction"),
        h4_direction = wave_map["H4"].get("direction"),
        h1_direction = wave_map["H1"].get("direction"),
        w1_pivots    = wave_map["W1"]["pivots"],
        current_price= current_price,
        h4_bos       = h4_bos,
        h1_bos       = h1_bos,
    )

    signal = build_signal(
        weekly_bias,
        daily_bias,
        h1_bias,
        confidence,
        weekly_pattern,
        daily_pattern,
        h1_pattern,
        conflict_result = conflict_result,
        bos             = bos,
        h1_elliott      = h1_elliott,
        w1_elliott      = w1_elliott,
        d1_elliott      = d1_elliott,
        h4_bos          = h4_bos,
        h1_bos          = h1_bos,
    )

    recommendation = build_recommendation(
        trend          = trend,
        elliott        = w1_elliott,
        bos            = bos,
        choch          = choch,
        volume         = volume,
        alignment      = alignment,
        wave_alignment = wave_alignment,
        confidence     = confidence,
        w1_elliott     = w1_elliott,
        d1_elliott     = d1_elliott,
        h1_elliott     = h1_elliott,
        h4_elliott     = h4_elliott,
        w1_direction   = wave_map["W1"].get("direction"),
        d1_direction   = wave_map["D1"].get("direction"),
        h4_direction   = wave_map["H4"].get("direction"),
        h4_bos         = h4_bos,
        h1_bos         = h1_bos,
        # FIX: الآن wave_map[tf]["correction_state"] موجود فعلياً
        # (بُني أعلاه بواسطة attach_correction_states)، فهذا
        # الاستدعاء يحصل على القيمة الصحيحة بدل None دائماً.
        w1_correction  = wave_map["W1"].get("correction_state"),
        d1_correction  = wave_map["D1"].get("correction_state"),
    )

    atr_h1 = calc_atr(timeframes.get("H1"), period=14)
    pip_multiplier = get_pip_multiplier(symbol)

    wave_context_w1 = build_wave_context(w1_elliott)
    wave_context_h1 = build_wave_context(h1_elliott)

    trade_setup = build_trade_setup(
        recommendation,
        w1_elliott,
        fib,
        pivots,
        wave_context_h1,
        current_price  = current_price,
        atr_h1         = atr_h1,
        pip_multiplier = pip_multiplier,
        h1_pivots      = wave_map["H1"]["pivots"],
        d1_pivots      = wave_map["D1"]["pivots"],
    )

    return {
        "entry"              : entry,
        "signal"             : signal,
        "elliott_rules"      : elliott_rules,
        "trend"              : trend,
        "trade_setup"        : trade_setup,
        "fib"                : fib,
        "volume"             : volume,
        "pivots"             : pivots,
        "wave"               : wave,
        "swings"             : swings,
        "wave_sequence"      : wave_sequence,
        "elliott"            : w1_elliott,
        "confidence"         : confidence,
        "wave_score"         : wave_score,
        "wave_context"       : wave_context,
        "market_wave_context": market_wave_context,
        "wave_map"           : wave_map,
        "wave_alignment"     : wave_alignment,
        "timeframes"         : summary,
        "alignment"          : alignment,
        "advanced_alignment" : advanced,
        "bos"                : bos,
        "h4_bos"             : h4_bos,
        "h1_bos"             : h1_bos,
        "choch"              : choch,
        "recommendation"     : recommendation,
        "current_price"      : current_price,
        "timeframe_structure": {
            "W1": weekly_structure,
            "D1": daily_structure,
            "H4": h4_structure,
            "H1": h1_structure
        }
    }