import datetime
import json
import re


class UIStreamLogger:
    """
    Structured logger that emits clean JSON entries for the frontend WebSocket.
    Each log is stored as a dict: {"type": "status"|"progress", "message": "...", ...}
    The WebSocket reads only NEW entries since the last read via get_new_entries().
    """

    def __init__(self):
        self._entries = []
        self._last_read_idx = 0

    def log(self, message: str):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        m = re.match(r'^PROGRESS\|(\d+)\|(.+)$', message)
        if m:
            entry = {
                "type": "progress",
                "percent": int(m.group(1)),
                "message": m.group(2).strip(),
                "ts": timestamp,
            }
        else:
            entry = {
                "type": "status",
                "message": message.strip(),
                "ts": timestamp,
            }
        self._entries.append(entry)
        print(f"[{timestamp}] {message}")

    def error(self, message: str):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        entry = {
            "type": "error",
            "message": message.strip(),
            "ts": timestamp,
        }
        self._entries.append(entry)
        print(f"[{timestamp}] ERROR: {message}")

    def get_new_entries(self) -> list:
        if self._last_read_idx >= len(self._entries):
            return []
        new = self._entries[self._last_read_idx:]
        self._last_read_idx = len(self._entries)
        return new

    def get_full_log(self) -> str:
        return "\n".join(e["message"] for e in self._entries)

    def clear(self):
        self._entries.clear()
        self._last_read_idx = 0


ui_logger = UIStreamLogger()
