from __future__ import annotations

MINI_BAR_WIDTH = 10


def format_duration(seconds: float) -> str:
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours:d}h{minutes:02d}m{secs:02d}s" if hours else f"{minutes:02d}m{secs:02d}s"


def render_bar(fraction: float, width: int = MINI_BAR_WIDTH) -> str:
    filled = int(round(fraction * width))
    return "█" * filled + "░" * (width - filled)
