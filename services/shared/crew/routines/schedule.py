"""Next-run maths for cron routines, in the routine's own timezone.

"Every day at 9:00" means 9:00 on the wall clock where the user lives, so the UTC time
moves when daylight saving starts or ends.
"""

import itertools
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter

from crew.errors import AppError


def _invalid(message: str) -> AppError:
    return AppError(422, "invalid_schedule", message)


def timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise _invalid("That timezone is not known.") from error


def validate(cron: str, tz_name: str) -> None:
    timezone(tz_name)
    if len(cron.split()) != 5 or not croniter.is_valid(cron):
        raise _invalid(
            "That schedule is not valid. Use five fields: minute hour day month weekday."
        )


def next_run(cron: str, tz_name: str, after: datetime) -> datetime:
    """The first time strictly after `after` that the schedule matches. Returned in UTC.

    Stepped through wall-clock time in the routine's zone, then checked against real time:
    a local time skipped in spring is passed over, and one repeated in autumn runs once.
    """
    validate(cron, tz_name)
    zone = timezone(tz_name)
    local = after.astimezone(zone)
    # croniter walks naive wall-clock time; we attach the zone to each candidate.
    walker = croniter(cron, local.replace(tzinfo=None))
    for _ in range(1000):
        naive: datetime = walker.get_next(datetime)
        candidate = naive.replace(tzinfo=zone)
        # A time that does not exist on this day (spring forward) does not round-trip.
        if candidate.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != naive:
            continue
        moment = candidate.astimezone(UTC)
        if moment > after.astimezone(UTC):
            return moment
    raise _invalid("That schedule never runs.")


def preview(cron: str, tz_name: str, now: datetime, count: int = 3) -> list[datetime]:
    runs: list[datetime] = []
    moment = now
    for _ in range(count):
        moment = next_run(cron, tz_name, moment)
        runs.append(moment)
    return runs


def shortest_gap(cron: str, tz_name: str, now: datetime) -> timedelta:
    """The smallest gap between the next few runs (to refuse schedules that fire too often)."""
    runs = preview(cron, tz_name, now, 6)
    return min(later - earlier for earlier, later in itertools.pairwise(runs))
