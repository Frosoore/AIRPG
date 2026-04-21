"""
core/time_system.py

Flexible time and calendar system for AIRPG.
Allows custom minutes per hour, hours per day, and named months.
"""

from __future__ import annotations
import json
from dataclasses import dataclass, field

@dataclass
class CalendarConfig:
    """Configuration for a custom calendar."""
    minutes_per_hour: int = 60
    hours_per_day: int = 24
    days_per_month: list[int] = field(default_factory=lambda: [30] * 12)
    month_names: list[str] = field(default_factory=lambda: [
        "Month 1", "Month 2", "Month 3", "Month 4", "Month 5", "Month 6",
        "Month 7", "Month 8", "Month 9", "Month 10", "Month 11", "Month 12"
    ])
    start_day: int = 1
    start_hour: int = 0
    start_minute: int = 0

    @property
    def minutes_per_day(self) -> int:
        return self.minutes_per_hour * self.hours_per_day

    @property
    def minutes_per_year(self) -> int:
        return sum(self.days_per_month) * self.minutes_per_day

    def to_json(self) -> str:
        return json.dumps({
            "mph": self.minutes_per_hour,
            "hpd": self.hours_per_day,
            "dpm": self.days_per_month,
            "months": self.month_names,
            "sd": self.start_day,
            "sh": self.start_hour,
            "sm": self.start_minute
        })

    @classmethod
    def from_json(cls, data_str: str) -> CalendarConfig:
        try:
            d = json.loads(data_str)
            return cls(
                minutes_per_hour=d.get("mph", 60),
                hours_per_day=d.get("hpd", 24),
                days_per_month=d.get("dpm", [30] * 12),
                month_names=d.get("months", ["Month " + str(i+1) for i in range(12)]),
                start_day=d.get("sd", 1),
                start_hour=d.get("sh", 0),
                start_minute=d.get("sm", 0)
            )
        except (json.JSONDecodeError, TypeError, AttributeError):
            return cls()

class TimeSystem:
    """Handles time conversion and formatting based on a CalendarConfig."""

    def __init__(self, config: CalendarConfig | None = None) -> None:
        self.config = config or CalendarConfig()

    def get_time_string(self, total_minutes: int) -> str:
        """Format total cumulative minutes into a human-readable calendar string."""
        cfg = self.config
        
        # Adjust by start time
        start_offset = ((cfg.start_day - 1) * cfg.minutes_per_day) + \
                       (cfg.start_hour * cfg.minutes_per_hour) + \
                       cfg.start_minute
        
        abs_mins = total_minutes + start_offset
        
        # Calculate Year
        year = (abs_mins // cfg.minutes_per_year) + 1
        rem_mins = abs_mins % cfg.minutes_per_year
        
        # Calculate Month and Day
        month_idx = 0
        mins_in_month = [d * cfg.minutes_per_day for d in cfg.days_per_month]
        for i, m_mins in enumerate(mins_in_month):
            if rem_mins < m_mins:
                month_idx = i
                break
            rem_mins -= m_mins
        
        day = (rem_mins // cfg.minutes_per_day) + 1
        rem_mins %= cfg.minutes_per_day
        
        hour = rem_mins // cfg.minutes_per_hour
        minute = rem_mins % cfg.minutes_per_hour
        
        month_name = cfg.month_names[month_idx] if month_idx < len(cfg.month_names) else "Unknown"
        
        # Simple phase detection based on fractional day
        from core.localization import tr
        day_progress = (hour * cfg.minutes_per_hour + minute) / cfg.minutes_per_day
        if 0.2 < day_progress < 0.35: phase = tr("dawn")
        elif 0.35 <= day_progress < 0.5: phase = tr("morning")
        elif 0.5 <= day_progress < 0.7: phase = tr("afternoon")
        elif 0.7 <= day_progress < 0.85: phase = tr("dusk")
        else: phase = tr("night")

        return tr("time_fmt", year=year, month=month_name, day=day, hour=f"{hour:02d}", minute=f"{minute:02d}", phase=phase)

    def components_to_minutes(self, day: int, hour: int, minute: int) -> int:
        """Convert a simplified (Day, Hour, Min) UI input back to cumulative session minutes."""
        # Note: This assumes Day 1 starts at 0 minutes in the SESSION, 
        # NOT accounting for start_offset (which is handled by get_time_string display).
        return ((day - 1) * self.config.minutes_per_day) + (hour * self.config.minutes_per_hour) + minute

    def minutes_to_components(self, total_minutes: int) -> tuple[int, int, int]:
        """Convert session minutes back to Day, Hour, Min."""
        cfg = self.config
        day = (total_minutes // cfg.minutes_per_day) + 1
        rem = total_minutes % cfg.minutes_per_day
        hour = rem // cfg.minutes_per_hour
        minute = rem % cfg.minutes_per_hour
        return day, hour, minute
