"""
fib_reaction_zone.py — تحديد مناطق التفاعل حول مستويات فيبوناتشي
══════════════════════════════════════════════════════════════════

✘ المشكلة:
  السعر نادراً ما يرتد من الرقم بالتمام
  بل من منطقة (Zone) حوله

✅ الحل:
  تحويل مستويات Fib إلى مناطق رد فعل (Reaction Zones)
  بنطاقات ±1% أو نسبة من ATR
"""

import pandas as pd
import numpy as np
from logger import log


class FibReactionZone:
    """
    تحويل مستويات Fibonacci إلى مناطق رد فعل مع ATR
    """
    
    # مستويات Fibonacci القياسية
    FIB_LEVELS = {
        0.236: "23.6%",
        0.382: "38.2%",
        0.5: "50%",
        0.618: "61.8%",
        0.786: "78.6%",
        1.0: "100%",
        1.272: "127.2%",
        1.618: "161.8%",
        2.0: "200%",
    }
    
    def __init__(self, rates: list, lookback: int = 100):
        """
        إعداد Fibonacci Zones
        
        Args:
            rates: قائمة الشموع
            lookback: عدد الشموع للبحث
        """
        self.rates = rates
        self.df = pd.DataFrame(rates).tail(lookback).reset_index(drop=True)
        self.atr = self._calculate_atr()
        self.zones = []
    
    def _calculate_atr(self, period: int = 14) -> float:
        """حساب ATR الحالي"""
        h = self.df["high"]
        l = self.df["low"]
        c = self.df["close"]
        
        tr1 = h - l
        tr2 = (h - c.shift()).abs()
        tr3 = (l - c.shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.ewm(com=period - 1, adjust=False).mean()
        
        return float(atr.iloc[-1]) if len(atr) > 0 else 1.0
    
    def create_zones(self, low_price: float, high_price: float, 
                     zone_width_pct: float = 0.01) -> list:
        """
        إنشاء Reaction Zones حول مستويات Fibonacci
        
        Args:
            low_price: أقل سعر
            high_price: أعلى سعر
            zone_width_pct: عرض المنطقة (نسبة مئوية)
        
        Returns:
            قائمة مناطق
        """
        if low_price >= high_price:
            return []
        
        price_range = high_price - low_price
        zone_width = price_range * zone_width_pct
        
        # استخدم ATR كبديل
        zone_width = max(zone_width, self.atr * 0.5)
        
        self.zones = []
        
        for level_ratio, level_name in self.FIB_LEVELS.items():
            # أرقام Retracement: بين 0 و 1
            if 0 <= level_ratio <= 1:
                fib_price = low_price + price_range * level_ratio
            # أرقام Extension: أكثر من 1
            else:
                fib_price = high_price + (high_price - low_price) * (level_ratio - 1)
            
            zone = {
                "level_ratio": level_ratio,
                "level_name": level_name,
                "center_price": round(fib_price, 2),
                "upper_bound": round(fib_price + zone_width / 2, 2),
                "lower_bound": round(fib_price - zone_width / 2, 2),
                "zone_width": round(zone_width, 2),
                "atr_distance": round(zone_width / self.atr, 2) if self.atr > 0 else 0,
                "is_active": False,
            }
            self.zones.append(zone)
        
        return self.zones
    
    def check_price_in_zone(self, current_price: float) -> dict | None:
        """
        فتش هل السعر في أي منطقة رد فعل
        
        Returns:
            منطقة إذا كان السعر بها، وإلا None
        """
        for zone in self.zones:
            if zone["lower_bound"] <= current_price <= zone["upper_bound"]:
                zone["is_active"] = True
                log.info(f"🔴 السعر {current_price} في Fib {zone['level_name']}")
                return zone
        
        return None
    
    def get_nearest_zone(self, current_price: float) -> dict | None:
        """
        الحصول على أقرب منطقة
        """
        if not self.zones:
            return None
        
        nearest = min(self.zones, 
                     key=lambda z: abs(current_price - z["center_price"]))
        
        distance = abs(current_price - nearest["center_price"])
        nearest["distance_to_zone"] = round(distance, 2)
        
        return nearest
    
    def get_zones_summary(self) -> str:
        """
        عرض ملخص من Zones
        """
        lines = [f"\n📄 Fibonacci Reaction Zones (ATR={self.atr:.2f}):\n"]
        
        for zone in self.zones:
            status = "🔴" if zone["is_active"] else "⚪"
            lines.append(
                f"{status} {zone['level_name']:>6} | "
                f"{zone['lower_bound']:.2f} - {zone['center_price']:.2f} - {zone['upper_bound']:.2f}"
            )
        
        return "\n".join(lines)
