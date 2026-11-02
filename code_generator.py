from datetime import datetime, timezone
import secrets


def format_project_code(sequence_number: int, year: int | None = None) -> str:
    """Generates unique deterministic project code: PRJ-2026-A001."""
    yr = year or datetime.now(timezone.utc).year
    bucket_idx = (max(1, sequence_number) - 1) // 999
    letter = chr(ord("A") + (bucket_idx % 26))
    num = ((max(1, sequence_number) - 1) % 999) + 1
    return f"PRJ-{yr}-{letter}{num:03d}"


def format_link_code(sequence_number: int, year: int | None = None) -> str:
    """Generates unique deterministic link code: LNK-2026-B001."""
    yr = year or datetime.now(timezone.utc).year
    bucket_idx = (max(1, sequence_number) - 1) // 999
    letter = chr(ord("B") + (bucket_idx % 25))
    num = ((max(1, sequence_number) - 1) % 999) + 1
    return f"LNK-{yr}-{letter}{num:03d}"


def generate_ai_session_code() -> str:
    """Generates unique AI session code: AIS-2026-XXXXXX."""
    yr = datetime.now(timezone.utc).year
    token = secrets.token_hex(3).upper()
    return f"AIS-{yr}-{token}"
