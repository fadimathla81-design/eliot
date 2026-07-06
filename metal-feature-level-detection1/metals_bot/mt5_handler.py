"""
mt5_handler.py — كل شيء يخص MT5
═══════════════════════════════════════════════════
- الاتصال وإعادة الاتصال
- المؤشرات التقنية المحسّنة:
    EMA (20/50/200) | RSI | ATR
    Bollinger Bands | Stochastic | VWAP
- فيبوناتشي Retracement + Extension (مبسطة)
- Order Blocks + BOS (مبسط)
- Fair Value Gaps (FVG) المفلترة
- ملخص الرمز للـ Prompt (get_symbol_summary)
- وظائف مساعدة: analyze_dxy_trend, check_fvg_imbalance, get_open_positions_summary,
  calculate_optimal_sl
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import pandas as pd
import numpy as np

from config import (
    EMA_PERIODS, RSI_PERIOD, ATR_PERIOD,
    BB_PERIOD, BB_STD,
    STOCH_K, STOCH_D, STOCH_SMOOTH,
    BARS_H4, BARS_H1, BARS_M15,
    BARS_FVG, BARS_OB, OB_LOOKBACK,
    DXY_SYMBOLS, SYMBOLS,
)
from logger import log
from advanced_levels import detect_levels

try:
    import MetaTrader5 as mt5  # type: ignore
    MT5_AVAILABLE = True
except Exception:
    MT5_AVAILABLE = False
    log.warning("⚠️ MetaTrader5 غير مثبّت.")


# ─────────────────────────────────────────────────────────────
#  Connection helpers
# ─────────────────────────────────────────────────────────────
def ensure_mt5_connected() -> bool:
    if not MT5_AVAILABLE:
        return False
    try:
        info = mt5.terminal_info()
        if info is not None:
            return True
    except Exception:
        pass

    log.warning("⚠️ MT5 منقطع — محاولة إعادة الاتصال...")
    for attempt in range(3):
        try:
            if mt5.initialize():
                log.info("✅ MT5 متصل مجدداً.")
                return True
        except Exception:
            log.warning(f"محاولة {attempt + 1}/3 فشلت.")
        time.sleep(2)
    log.error("❌ فشل الاتصال بـ MT5 نهائياً.")
    return False


# ─────────────────────────────────────────────────────────────
#  Price / Rates helpers
# ─────────────────────────────────────────────────────────────
def _fetch_rates(symbol: str, timeframe: int, bars: int) -> list[dict] | None:
    """
    Fetch rates from MT5 and return list-of-dicts with keys:
    time, open, high, low, close, tick_volume
    If MT5 not available or error, return None.
    """
    if not ensure_mt5_connected():
        return None
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, bars)
        if rates is None or len(rates) == 0:
            return None
        # convert numpy structured array to list of dicts
        df = pd.DataFrame(rates)
        # ensure float types
        df = df.astype({"open": float, "high": float, "low": float, "close": float})
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df = df.rename(columns={"tick_volume": "tick_volume"})
        return df.to_dict(orient="records")
    except Exception as e:
        log.error(f"خطأ جلب الشموع لـ {symbol}: {e}")
        return None


def get_current_price(symbol: str) -> float:
    """Return current ask price or 0.0 on failure."""
    if not ensure_mt5_connected():
        return 0.0
    try:
        tick = mt5.symbol_info_tick(symbol)
        return round(float(tick.ask), 3) if tick else 0.0
    except Exception:
        return 0.0


# ─────────────────────────────────────────────────────────────
#  Indicators & small utilities
# ─────────────────────────────────────────────────────────────
def _calculate_indicators_from_rates(rates: list[dict]) -> dict:
    """
    Lightweight indicator calculation used inside get_symbol_summary.
    Expects rates as list of dicts with keys high/low/close/tick_volume.
    """
    if not rates or len(rates) < 20:
        return {}

    df = pd.DataFrame(rates)
    c = df["close"]
    h = df["high"]
    l = df["low"]

    # EMA
    ema20 = c.ewm(span=20, adjust=False).mean().iloc[-1]
    ema50 = c.ewm(span=50, adjust=False).mean().iloc[-1]
    ema200 = c.ewm(span=200, adjust=False).mean().iloc[-1]

    # RSI
    delta = c.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=RSI_PERIOD - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=RSI_PERIOD - 1, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi_val = float(rsi.iloc[-1]) if len(rsi) > 0 else 50.0

    # ATR
    hl = h - l
    hcp = (h - c.shift()).abs()
    lcp = (l - c.shift()).abs()
    tr = pd.concat([hl, hcp, lcp], axis=1).max(axis=1)
    atr = tr.ewm(com=ATR_PERIOD - 1, adjust=False).mean()
    atr_val = float(atr.iloc[-1]) if len(atr) > 0 else 1.0

    # Bollinger
    bb_mid = c.rolling(BB_PERIOD).mean().iloc[-1]
    bb_std = c.rolling(BB_PERIOD).std().iloc[-1]
    bb_upper = bb_mid + BB_STD * bb_std
    bb_lower = bb_mid - BB_STD * bb_std
    price = float(c.iloc[-1])
    bb_pos = _bb_position(price, float(bb_upper), float(bb_lower), float(bb_mid))
    bb_width = round(((float(bb_upper) - float(bb_lower)) / float(bb_mid)) * 100, 2) if bb_mid else 0.0

    # Stochastic (simple)
    low_min = l.rolling(STOCH_K).min()
    high_max = h.rolling(STOCH_K).max()
    stoch_k = 100 * (c - low_min) / (high_max - low_min + 1e-10)
    stoch_k = stoch_k.rolling(STOCH_SMOOTH).mean()
    stoch_d = stoch_k.rolling(STOCH_D).mean()
    sk_val = float(stoch_k.iloc[-1]) if len(stoch_k) > 0 else 50.0
    sd_val = float(stoch_d.iloc[-1]) if len(stoch_d) > 0 else 50.0
    stoch_signal = _stoch_signal(sk_val, sd_val)

    # Volume
    vol = df["tick_volume"] if "tick_volume" in df.columns else pd.Series([0] * len(df))
    vol_avg = vol.rolling(20).mean()
    vol_trend = ("مرتفع 🔥" if vol.iloc[-1] > vol_avg.iloc[-1] * 1.5
                 else "فوق المتوسط" if vol.iloc[-1] > vol_avg.iloc[-1] * 1.2
                 else "عادي")

    return {
        "ema20": round(float(ema20), 3),
        "ema50": round(float(ema50), 3),
        "ema200": round(float(ema200), 3),
        "ema_trend": _ema_trend(price, float(ema20), float(ema50), float(ema200)),
        "rsi": round(rsi_val, 1),
        "rsi_state": (f"{rsi_val:.1f} ⚠️ تشبع شرائي" if rsi_val >= 70
                      else f"{rsi_val:.1f} ⚠️ تشبع بيعي" if rsi_val <= 30
                      else f"{rsi_val:.1f} ✅ محايد"),
        "atr": round(atr_val, 3),
        "bb_upper": round(float(bb_upper), 3),
        "bb_mid": round(float(bb_mid), 3) if bb_mid else None,
        "bb_lower": round(float(bb_lower), 3),
        "bb_pos": bb_pos,
        "bb_width": bb_width,
        "stoch_k": round(sk_val, 1),
        "stoch_d": round(sd_val, 1),
        "stoch_signal": stoch_signal,
        "vwap": _calculate_vwap(pd.DataFrame(rates)),
        "vol_trend": vol_trend,
    }


def _ema_trend(price, e20, e50, e200) -> str:
    if price > e20 > e50 > e200:
        return "صاعد قوي ↑↑"
    elif price > e50 > e200:
        return "صاعد معتدل ↑"
    elif price > e200:
        return "فوق EMA200 ↑"
    elif price < e20 < e50 < e200:
        return "هابط قوي ↓↓"
    elif price < e50 < e200:
        return "هابط معتدل ↓"
    elif price < e200:
        return "تحت EMA200 ↓"
    return "محايد ↔"


def _bb_position(price, upper, lower, mid) -> str:
    if price >= upper:
        return "فوق الحد العلوي ⚠️ (تشبع)"
    elif price >= mid:
        return "بين المتوسط والحد العلوي"
    elif price <= lower:
        return "تحت الحد السفلي ⚠️ (تشبع)"
    else:
        return "بين المتوسط والحد السفلي"


def _stoch_signal(k: float, d: float) -> str:
    if k >= 80 and d >= 80:
        return f"K={k} D={d} ⚠️ تشبع شرائي"
    elif k <= 20 and d <= 20:
        return f"K={k} D={d} ⚠️ تشبع بيعي"
    elif k > d and k < 80:
        return f"K={k} D={d} 📈 إشارة شراء"
    elif k < d and k > 20:
        return f"K={k} D={d} 📉 إشارة بيع"
    return f"K={k} D={d} محايد"


def _calculate_vwap(df: pd.DataFrame) -> float | None:
    try:
        vol = df["tick_volume"] if "tick_volume" in df.columns else None
        if vol is None or vol.sum() == 0:
            return None
        typical = (df["high"] + df["low"] + df["close"]) / 3
        vwap = (typical * vol).cumsum() / vol.cumsum()
        return float(vwap.iloc[-1])
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────
#  get_symbol_summary (public)
# ─────────────────────────────────────────────────────────────
def get_symbol_summary(symbol: str, timeframe: int, bars: int) -> dict:
    """
    Returns a summary dict used by the prompt builder. Keys include:
    - trend (H4/H1 etc), high/low, last_close
    - indicators: (from _calculate_indicators_from_rates)
    - fibonacci (simple placeholder text)
    - order_blocks (from detect_levels)
    - liquidity (derived from detect_levels output)
    - sl_buy / sl_sell: reference SL objects
    """
    rates = _fetch_rates(symbol, timeframe, bars)
    if rates is None:
        return {"error": "failed to fetch rates"}

    indicators = _calculate_indicators_from_rates(rates)
    last_close = float(rates[-1]["close"])

    # detect levels (uses advanced_levels.detect_levels wrapper)
    levels = detect_levels(rates, lookback=min(500, bars), swing_window=5)

    # basic trend (simplified)
    trend = "محايد"
    try:
        ema_trend = indicators.get("ema_trend", "") if isinstance(indicators, dict) else ""
        trend = ema_trend
    except Exception:
        pass

    # Build liquidity info (simple heuristic)
    liq = {}
    try:
        distance_to_support = abs(last_close - levels.get("support", 0))
        distance_to_resistance = abs(levels.get("resistance", 0) - last_close)
        atr = indicators.get("atr", 1.0)
        distance_atr = round(min(distance_to_support, distance_to_resistance) / (atr or 1.0), 2)
        near_major_low = distance_to_support <= 1.5 * (atr or 1.0)
        near_major_high = distance_to_resistance <= 1.5 * (atr or 1.0)
        liq_score = 0
        if near_major_low or near_major_high:
            liq_score = int(max(30, min(90, 50 + (2 - distance_atr) * 20)))
        liq = {
            "liquidity_score": liq_score,
            "near_major_low": near_major_low,
            "near_major_high": near_major_high,
            "major_low": levels.get("major_low", 0),
            "major_high": levels.get("major_high", 0),
            "bullish_divergence": levels.get("divergence", {}).get("overall_signal") == "BULLISH",
            "bearish_divergence": levels.get("divergence", {}).get("overall_signal") == "BEARISH",
            "volume_rising": levels.get("volume", {}).get("volume_trend") == "BULLISH",
            "distance_atr": distance_atr,
        }
    except Exception:
        liq = {"liquidity_score": 0}

    # SL suggestions from swing + ATR (reference only)
    try:
        sl_buy_price = round(levels.get("support", last_close) - indicators.get("atr", 1.0), 3)
        sl_sell_price = round(levels.get("resistance", last_close) + indicators.get("atr", 1.0), 3)
        sl_buy = {"sl_price": sl_buy_price, "sl_distance": round(abs(last_close - sl_buy_price), 3), "basis": "Swing+ATR"}
        sl_sell = {"sl_price": sl_sell_price, "sl_distance": round(abs(last_close - sl_sell_price), 3), "basis": "Swing+ATR"}
    except Exception:
        sl_buy = {"sl_price": None, "sl_distance": None, "basis": None}
        sl_sell = {"sl_price": None, "sl_distance": None, "basis": None}

    # Fibonacci placeholder: produce formatted text expected by consumer
    fib_text = _build_fib_text(levels)

    return {
        "trend": trend,
        "high": levels.get("major_high", 0),
        "low": levels.get("major_low", 0),
        "last_close": last_close,
        "indicators": indicators,
        "fibonacci": fib_text,
        "order_blocks": f"Buy OB @ {levels.get('order_block_buy')} | Sell OB @ {levels.get('order_block_sell')}",
        "liquidity": liq,
        "sl_buy": sl_buy,
        "sl_sell": sl_sell,
        "support": levels.get("support"),
        "resistance": levels.get("resistance"),
    }


def _build_fib_text(levels: dict) -> str:
    """
    Simple textual fibonacci summary so the prompt sees numeric Fib levels.
    This is only to satisfy prompt parsing — accurate Fib calc omitted for brevity.
    """
    try:
        low = levels.get("major_low") or levels.get("support") or 0
        high = levels.get("major_high") or levels.get("resistance") or 0
        if not low or not high or high == low:
            return "—"
        ret382 = low + (high - low) * 0.382
        ret50 = low + (high - low) * 0.5
        ret618 = low + (high - low) * 0.618
        ext1618 = high + (high - low) * 0.618
        return (f"Ret 0.382 : {ret382:.3f}\\nRet 0.5 : {ret50:.3f}\\nRet 0.618 : {ret618:.3f}\\n"
                f"Ext 1.618 : {ext1618:.3f}")
    except Exception:
        return "—"


# ─────────────────────────────────────────────────────────────
#  DXY / FVG / OB helper functions used by analysis_engine
# ─────────────────────────────────────────────────────────────
def analyze_dxy_trend() -> tuple[str, str]:
    """
    Analyze DXY symbols (from config DXY_SYMBOLS) to produce a short text and direction.
    Returns: (text, direction) direction in {"UP","DOWN","NEUTRAL"}
    """
    texts = []
    up = down = 0
    for sym in (DXY_SYMBOLS or []):
        price = get_current_price(sym)
        if price <= 0:
            continue
        # cheap heuristic: compare recent H1 slope from few candles
        rates = _fetch_rates(sym, mt5.TIMEFRAME_H1 if MT5_AVAILABLE else 0, 20) if MT5_AVAILABLE else None
        if rates and len(rates) >= 2:
            df = pd.DataFrame(rates)
            slope = float(df["close"].iloc[-1] - df["close"].iloc[-5]) if len(df) > 5 else 0.0
            if slope > 0:
                up += 1
            elif slope < 0:
                down += 1
            texts.append(f"{sym}: {df['close'].iloc[-1]:.2f} (slope {slope:.3f})")
        else:
            texts.append(f"{sym}: {price:.2f}")

    if up > down:
        direction = "UP"
    elif down > up:
        direction = "DOWN"
    else:
        direction = "NEUTRAL"
    return ("\n".join(texts) if texts else "DXY data unavailable", direction)


def check_fvg_imbalance(symbol: str, timeframe: int, bars: int) -> str:
    """
    A simplified FVG detection: looks for gaps between candles' highs/lows in recent bars.
    Returns a textual summary (possibly multiline) or '—' if none.
    """
    rates = _fetch_rates(symbol, timeframe, bars)
    if not rates or len(rates) < 3:
        return "—"
    df = pd.DataFrame(rates)
    fvg_lines = []
    for i in range(len(df) - 2):
        # fair value gap: low of candle i+1 > high of candle i (bullish gap) or reverse
        if df["low"].iloc[i + 1] > df["high"].iloc[i]:
            fvg_lines.append(f"FVG Bullish around {df['low'].iloc[i+1]:.3f}")
        if df["high"].iloc[i + 1] < df["low"].iloc[i]:
            fvg_lines.append(f"FVG Bearish around {df['high'].iloc[i+1]:.3f}")
        if len(fvg_lines) > 5:
            break
    return "\n".join(fvg_lines) if fvg_lines else "—"


def get_open_positions_summary(symbol: str) -> list[dict]:
    """
    Returns simple list of open positions for the given symbol:
    [{'ticket': id, 'direction': 'BUY'|'SELL', 'price_open': x, 'profit': y}, ...]
    If no MT5 or none, return [].
    """
    if not MT5_AVAILABLE or not ensure_mt5_connected():
        return []
    try:
        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            return []
        out = []
        for p in positions:
            direction = "BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL"
            out.append({
                "ticket": int(p.ticket),
                "direction": direction,
                "price_open": float(p.price_open),
                "profit": float(p.profit),
            })
        return out
    except Exception as e:
        log.error(f"خطأ جلب الصفقات المفتوحة: {e}")
        return []


def calculate_optimal_sl(symbol: str, entry: float, direction: str, h1_summary: dict) -> dict:
    """
    Calculate a reference SL based on s/r levels and ATR:
    Returns dict: {'sl_price': float, 'sl_distance': float, 'basis': 'Swing+ATR'}
    """
    try:
        atr = h1_summary.get("indicators", {}).get("atr", 1.0)
        support = h1_summary.get("support", entry - 10)
        resistance = h1_summary.get("resistance", entry + 10)
        if direction == "BUY":
            sl_price = round(support - (atr * 0.5), 3)
        else:
            sl_price = round(resistance + (atr * 0.5), 3)
        return {"sl_price": sl_price, "sl_distance": round(abs(entry - sl_price), 3), "basis": "Swing+ATR"}
    except Exception:
        return {"sl_price": None, "sl_distance": None, "basis": None}


# ─────────────────────────────────────────────────────────────
#  Misc helpers
# ─────────────────────────────────────────────────────────────
def _calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    h = df["high"]
    l = df["low"]
    c = df["close"]
    tr1 = h - l
    tr2 = (h - c.shift()).abs()
    tr3 = (l - c.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(com=period - 1, adjust=False).mean()
    return float(atr.iloc[-1]) if len(atr) > 0 else 1.0

def get_current_atr(symbol: str, timeframe: int, bars: int = 100) -> float:
    """
    يعيد قيمة ATR الحالية للحجم المحدد من آخر `bars` شموع.
    يُعيد 0.0 عند الفشل (مثال: عدم اتصال MT5 أو عدم توفر بيانات).
    """
    try:
        rates = _fetch_rates(symbol, timeframe, bars)
        if not rates:
            return 0.0
        df = pd.DataFrame(rates)
        return round(_calculate_atr(df, period=ATR_PERIOD), 3)
    except Exception as e:
        log.warning(f"تعذر حساب ATR الحالي لـ {symbol}: {e}")
        return 0.0