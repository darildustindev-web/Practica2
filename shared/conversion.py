"""Una recotización explícita debe ser posterior a la operación persistida."""
from datetime import datetime, timezone


def newer_conversion(request, code, timestamp):
    if not request.revalue or code == request.verification_code or not timestamp:
        return False
    previous = timestamp if isinstance(timestamp, datetime) else datetime.fromisoformat(str(timestamp).replace('Z', '+00:00'))
    if previous.tzinfo is None:
        previous = previous.replace(tzinfo=timezone.utc)
    return request.converted_at > previous
