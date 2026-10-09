from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple
from .config import AreaConfig, MobilityConfig, PointOfInterest
from .mobility.poi import default_festival_pois

DENSE_AREA_FRACTION = 0.15
DENSE_POPULATION_SHARE = 0.70

# Layout of mobility.poi.default_festival_pois: (x/w, y/h, weight).
_POI_LAYOUT = ((0.25, 0.75, 4.0), (0.80, 0.70, 2.0), (0.55, 0.35, 3.0), (0.50, 0.05, 1.0))


@dataclass(frozen=True)
class SitePreset:
    num_festivaliers: int
    width_m: float
    height_m: float


# ~3 m^2 per person on a 1.4:1 site, whatever the size.
SITE_PRESETS: Dict[str, SitePreset] = {
    "small": SitePreset(4000, 130.0, 93.0),
    "medium": SitePreset(10000, 205.0, 146.0),
    "large": SitePreset(30000, 355.0, 253.0),
    "extra-large": SitePreset(60000, 502.0, 359.0),
}


def site_area(size: str) -> AreaConfig:
    preset = SITE_PRESETS[size]
    return AreaConfig(width_m=preset.width_m, height_m=preset.height_m)


def dense_zone_pois(
    area: AreaConfig, area_fraction: float = DENSE_AREA_FRACTION
) -> Tuple[PointOfInterest, ...]:
    # Square sides are proportional to sqrt(weight) so every POI has the same
    # density; centres are pulled inside the site so no square gets clamped
    # (a clamped square would silently shrink the dense zone).
    total_weight = sum(w for _, _, w in _POI_LAYOUT)
    pois = []
    for fx, fy, weight in _POI_LAYOUT:
        side = math.sqrt(area_fraction * area.width_m * area.height_m * weight / total_weight)
        r = side / 2.0
        x = min(max(fx * area.width_m, r), area.width_m - r)
        y = min(max(fy * area.height_m, r), area.height_m - r)
        pois.append(PointOfInterest(x=x, y=y, radius_m=r, weight=weight))
    return tuple(pois)


def crowd_mobility_config(
    area: AreaConfig,
    dense_area_fraction: float = DENSE_AREA_FRACTION,
    dense_population_share: float = DENSE_POPULATION_SHARE,
) -> MobilityConfig:
    # Background visits also land in the dense zone with probability
    # dense_area_fraction, hence share = (1 - bg) + bg * fraction.
    background = (1.0 - dense_population_share) / (1.0 - dense_area_fraction)
    return MobilityConfig(
        points_of_interest=dense_zone_pois(area, dense_area_fraction),
        background_probability=background,
    )


def resolve_cli_args(args: Any, default_num_festivaliers: int, error: Callable[[str], Any]) -> None:
    # Idempotent: a resolved --size already carries its preset's festivaliers.
    if args.size is not None:
        preset_count = SITE_PRESETS[args.size].num_festivaliers
        if args.num_festivaliers not in (None, preset_count):
            error(f"--size {args.size} fixe {preset_count} festivaliers, incompatible avec --num-festivaliers {args.num_festivaliers}")
        args.num_festivaliers = preset_count
        if args.mobility is None:
            args.mobility = "poi"
    elif args.num_festivaliers is None:
        args.num_festivaliers = default_num_festivaliers
    if args.mobility is None:
        args.mobility = "random_waypoint"


def build_site(
    size: Optional[str], num_festivaliers: int, mobility: str
) -> Tuple[int, AreaConfig, MobilityConfig]:
    if size is None:
        area = AreaConfig()
        pois = default_festival_pois(area) if mobility == "poi" else ()
        return num_festivaliers, area, MobilityConfig(points_of_interest=pois)
    area = site_area(size)
    mobility_config = crowd_mobility_config(area) if mobility == "poi" else MobilityConfig()
    return SITE_PRESETS[size].num_festivaliers, area, mobility_config
