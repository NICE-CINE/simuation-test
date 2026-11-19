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


def crowd_loss_db(distance_m: float, density_per_m2: float, body_loss_db: float, body_width_m: float) -> float:
    return body_loss_db * density_per_m2 * body_width_m * distance_m


def crowd_range_m(radio: RadioParams, density_per_m2: float, body_loss_db: float, body_width_m: float) -> float:
    # Where the mean margin, bodies included, reaches zero.
    high = max_range_m(radio)
    if body_loss_db <= 0.0 or density_per_m2 <= 0.0:
        return high
    low = radio.reference_distance_m
    if link_margin_db(low, radio) - crowd_loss_db(low, density_per_m2, body_loss_db, body_width_m) <= 0.0:
        return low
    for _ in range(40):
        mid = (low + high) / 2.0
        if link_margin_db(mid, radio) - crowd_loss_db(mid, density_per_m2, body_loss_db, body_width_m) > 0.0:
            low = mid
        else:
            high = mid
    return low
