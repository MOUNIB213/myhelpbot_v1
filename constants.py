import hashlib
import json
from pathlib import Path

REQUIRED_UNAUTHORIZED_MESSAGE = (
    "هذا البوت خاص ولا تملك صلاحية استخدامه. يرجى التواصل مع مالك البوت للحصول على إمكانية الوصول."
)

DEFAULT_ALLOWED_SECTIONS = [
    "ai",
    "projects",
    "links",
    "notes",
    "tasks",
    "reminders",
    "favorites",
    "search",
    "account",
    "settings",
]


def verify_backup_file_integrity(file_path: str, expected_sha256: str) -> bool:
    p = Path(file_path)
    if not p.exists() or not p.is_file():
        return False
    actual = hashlib.sha256(p.read_bytes()).hexdigest()
    if actual != expected_sha256:
        return False
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return "version" in data and "projects" in data and "links" in data
    except Exception:
        return False
