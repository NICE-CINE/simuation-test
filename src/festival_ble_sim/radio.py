from __future__ import annotations
import math
from .config import RadioParams


def max_range_m(radio: RadioParams) -> float:
    max_loss_db = radio.tx_power_dbm - radio.receiver_sensitivity_dbm
    exponent = (max_loss_db - radio.reference_loss_db) / (10.0 * radio.path_loss_exponent)
    return radio.reference_distance_m * (10.0**exponent)


def received_power_dbm(distance_m: float, radio: RadioParams) -> float:
    effective_distance = max(distance_m, radio.reference_distance_m)
    path_loss_db = radio.reference_loss_db + 10.0 * radio.path_loss_exponent * math.log10(
        effective_distance / radio.reference_distance_m
    )
    return radio.tx_power_dbm - path_loss_db


def link_margin_db(distance_m: float, radio: RadioParams) -> float:
    return received_power_dbm(distance_m, radio) - radio.receiver_sensitivity_dbm
