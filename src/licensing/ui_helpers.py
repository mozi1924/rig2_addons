import datetime as _dt


def format_duration_compact(total_seconds):
    total_seconds = int(max(0, total_seconds or 0))
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)

    parts = []
    if days:
        parts.append(f"{days}d")
    if days or hours:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


def format_expiry_label(total_seconds, *, expired_label="Expired", suffix="remaining"):
    total_seconds = int(total_seconds or 0)
    if total_seconds <= 0:
        return expired_label
    return f"{format_duration_compact(total_seconds)} {suffix}"


def format_timestamp_local(timestamp_value):
    timestamp_value = float(timestamp_value or 0)
    if timestamp_value <= 0:
        return "Unknown"
    return _dt.datetime.fromtimestamp(timestamp_value).strftime("%Y-%m-%d %H:%M")


def format_heartbeat_label(status):
    if status.get("heartbeat_in_flight"):
        return "syncing..."

    failures = int(status.get("consecutive_heartbeat_failures", 0) or 0)
    overdue_seconds = int(status.get("heartbeat_overdue_seconds", 0) or 0)

    if overdue_seconds > 0:
        return f"overdue by {format_duration_compact(overdue_seconds)}"
    if failures > 0:
        return f"{failures} failed attempts"
    if status.get("last_heartbeat_at"):
        return "healthy"
    return "pending"
