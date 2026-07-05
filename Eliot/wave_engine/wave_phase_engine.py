# wave_engine/wave_phase_engine.py

from wave_engine.bias_engine import get_bias_from_elliott


def detect_active_phase(elliott, direction):

    pattern = elliott.get("pattern")
    current = elliott.get("current_wave")

    # التصحيحات
    if pattern in ("ABC", "zigzag", "flat"):

        return {
            "phase": "correction",
            "direction": direction
        }

    # الموجات الدافعة
    return {
        "phase": "impulse",
        "direction": direction
    }


def detect_primary_trend(elliott, direction):

    return get_bias_from_elliott(
        elliott,
        direction
    )