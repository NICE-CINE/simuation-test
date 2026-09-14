from __future__ import annotations
from festival_ble_sim.config import SimulationConfig
from festival_ble_sim.metrics import format_report
from festival_ble_sim.simulation import run_simulation


def main() -> None:
    config = SimulationConfig()
    report = run_simulation(config)
    text = format_report(report)
    print(text)
    with open("rapport_simulation.txt", "w", encoding="utf-8") as f:
        f.write(text)


if __name__ == "__main__":
    main()
