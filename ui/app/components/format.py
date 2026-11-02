from datetime import UTC, datetime


def duration(seconds: float) -> str:
    """4000 -> '1h 6m 40s'."""
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    parts = []
    if days:
        parts.append(f"{days}d")
    if days or hours:
        parts.append(f"{hours}h")
    if days or hours or minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


def ago(timestamp: str | None, now: datetime | None = None) -> str:
    """An ISO timestamp as 'never' or '2h 5m 3s ago'."""
    if not timestamp:
        return "never"
    moment = datetime.fromisoformat(timestamp)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return f"{duration(((now or datetime.now(UTC)) - moment).total_seconds())} ago"
