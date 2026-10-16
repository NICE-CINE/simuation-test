import pytest
from festival_ble_sim.config import SimulationConfig
from festival_ble_sim.overrides import apply_cli_overrides, apply_overrides


def test_overrides_reach_nested_fields_with_the_right_types():
    config = apply_overrides(SimulationConfig(), [
        "traffic.message_ttl_s=900",
        "mobility.group.split_probability=0.5",
        "social.outside_friends_range=0,4",
        "churn.enabled=True",
        "traffic.message_ttl_hops=None",
        "beacons.placement=manual",
        "ble.phone_radio.tx_power_dbm=-6",
    ])
    assert config.traffic.message_ttl_s == 900.0 and isinstance(config.traffic.message_ttl_s, float)
    assert config.mobility.group.split_probability == 0.5
    assert config.social.outside_friends_range == (0, 4)
    assert config.churn.enabled is True
    assert config.traffic.message_ttl_hops is None
    assert config.beacons.placement == "manual"
    assert config.ble.phone_radio.tx_power_dbm == -6.0


@pytest.mark.parametrize("override, message", [
    ("traffic.ttl=3", "message_ttl_s"),
    ("traffic=3", "groupe de reglages"),
    ("duration_s.x=3", "pas de sous-champs"),
    ("traffic.message_ttl_s", "chemin=valeur"),
    ("social.no_friend_fraction=2", "no_friend_fraction"),
])
def test_bad_overrides_are_refused_with_a_clear_message(override, message):
    with pytest.raises(ValueError, match=message):
        apply_overrides(SimulationConfig(), [override])


def test_cli_cooldown_follows_an_overridden_ttl_unless_given():
    base = SimulationConfig(cooldown_s=1800.0)
    assert apply_cli_overrides(base, ["traffic.message_ttl_s=600"], None).cooldown_s == 600.0
    assert apply_cli_overrides(base, ["traffic.message_ttl_s=600"], 1800.0).cooldown_s == 1800.0
    assert apply_cli_overrides(base, ["traffic.message_ttl_s=600", "cooldown_s=60"], None).cooldown_s == 60.0
