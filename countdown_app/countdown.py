from datetime import datetime, timedelta
from typing import Dict, Optional
from dataclasses import dataclass


@dataclass(frozen=True)
class CountdownResult:
    name: str
    target: datetime
    delta: timedelta
    is_past: bool


class CountDown:
    def __init__(self, target_dates: Dict[str, datetime]):
        self.target_dates = target_dates

    def calculate_date_delta(
        self,
        now: Optional[datetime] = None
    ) -> Dict[str, CountdownResult]:
        """
        Calculate time delta from now to each target date.

        Returns:
            Dict[target_name, CountdownResult]
        """
        now = now or datetime.now()
        results: Dict[str, CountdownResult] = {}

        for name, target_dt in self.target_dates.items():
            delta = target_dt - now
            results[name] = CountdownResult(
                name=name,
                target=target_dt,
                delta=delta,
                is_past=delta.total_seconds() < 0,
            )

        return results

    @staticmethod
    def breakdown(delta: timedelta):
        """
        Convert timedelta to absolute days
        """
        total_seconds = int(abs(delta.total_seconds()))

        days, remainder = divmod(total_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)

        return {
            "days": days,
            "hours": hours,
            "minutes": minutes,
            "seconds": seconds,
        }