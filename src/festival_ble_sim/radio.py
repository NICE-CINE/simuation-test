from __future__ import annotations
import math
import random
from typing import Optional
from .config import RadioParams


def max_range_m(radio: RadioParams) -> float:
    max_loss_db = radio.tx_power_dbm - radio.receiver_sensitivity_dbm
    exponent = (max_loss_db - radio.reference_loss_db) / (10.0 * radio.path_loss_exponent)
    return radio.reference_distance_m * (10.0**exponent)


def received_power_dbm(distance_m: float, radio: RadioParams, rng: Optional[random.Random] = None) -> float:
    effective_distance = max(distance_m, radio.reference_distance_m)
    path_loss_db = radio.reference_loss_db + 10.0 * radio.path_loss_exponent * math.log10(
        effective_distance / radio.reference_distance_m
    )
    mean_dbm = radio.tx_power_dbm - path_loss_db
    # Log-normal shadow fading: resampled on every call (a fresh random
    # obstruction state), not held per-link, since callers already
    # recompute per contact-check tick — matching a block-fading
    # assumption at that timescale rather than tracking correlated fades.
    if rng is not None and radio.shadowing_std_db > 0.0:
        mean_dbm += rng.gauss(0.0, radio.shadowing_std_db)
    return mean_dbm


def link_margin_db(distance_m: float, radio: RadioParams, rng: Optional[random.Random] = None) -> float:
    return received_power_dbm(distance_m, radio, rng) - radio.receiver_sensitivity_dbm
