import random
import pytest
from festival_ble_sim.config import RadioParams
from festival_ble_sim.radio import link_margin_db, max_range_m, received_power_dbm


def _radio(**overrides) -> RadioParams:
    defaults = dict(
        tx_power_dbm=0.0,
        path_loss_exponent=2.0,
        reference_distance_m=1.0,
        reference_loss_db=40.0,
        receiver_sensitivity_dbm=-90.0,
    )
    defaults.update(overrides)
    return RadioParams(**defaults)


def test_received_power_equals_tx_minus_reference_loss_at_reference_distance():
    radio = _radio()
    assert received_power_dbm(1.0, radio) == pytest.approx(radio.tx_power_dbm - radio.reference_loss_db)


def test_received_power_decreases_monotonically_with_distance():
    radio = _radio()
    powers = [received_power_dbm(d, radio) for d in (1.0, 10.0, 50.0, 100.0)]
    assert powers == sorted(powers, reverse=True)


def test_max_range_m_matches_received_power_at_threshold():
    radio = _radio()
    range_m = max_range_m(radio)
    assert received_power_dbm(range_m, radio) == pytest.approx(radio.receiver_sensitivity_dbm, abs=1e-6)


def test_higher_tx_power_increases_max_range():
    weak = _radio(tx_power_dbm=-10.0)
    strong = _radio(tx_power_dbm=10.0)
    assert max_range_m(strong) > max_range_m(weak)


def test_higher_path_loss_exponent_shrinks_max_range():
    open_field = _radio(path_loss_exponent=2.0)
    obstructed = _radio(path_loss_exponent=3.5)
    assert max_range_m(obstructed) < max_range_m(open_field)


def test_link_margin_is_zero_at_max_range():
    radio = _radio()
    assert link_margin_db(max_range_m(radio), radio) == pytest.approx(0.0, abs=1e-6)


def test_link_margin_is_positive_close_and_negative_beyond_range():
    radio = _radio()
    range_m = max_range_m(radio)
    assert link_margin_db(range_m / 2, radio) > 0.0
    assert link_margin_db(range_m * 2, radio) < 0.0


def test_zero_shadowing_is_deterministic_regardless_of_rng():
    radio = _radio(shadowing_std_db=0.0)
    rng = random.Random(1)
    samples = {received_power_dbm(20.0, radio, rng) for _ in range(20)}
    assert len(samples) == 1


def test_no_rng_never_applies_shadowing_even_when_configured():
    radio = _radio(shadowing_std_db=10.0)
    assert received_power_dbm(20.0, radio) == pytest.approx(received_power_dbm(20.0, radio))


def test_shadowing_scatters_received_power_around_the_deterministic_mean():
    radio = _radio(shadowing_std_db=6.0)
    mean = received_power_dbm(20.0, radio)
    rng = random.Random(2)
    samples = [received_power_dbm(20.0, radio, rng) for _ in range(500)]
    assert len(set(samples)) > 1
    sampled_mean = sum(samples) / len(samples)
    assert sampled_mean == pytest.approx(mean, abs=1.0)


def test_shadowing_can_push_margin_negative_inside_the_deterministic_range():
    radio = _radio(shadowing_std_db=8.0)
    range_m = max_range_m(radio)
    rng = random.Random(3)
    margins = [link_margin_db(range_m * 0.9, radio, rng) for _ in range(500)]
    assert any(m < 0.0 for m in margins)
    assert any(m > 0.0 for m in margins)
