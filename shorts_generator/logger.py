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
        m_render = re.match(r'^RENDER_STATUS\|(\d+)\|(.+)$', message)
        if m_render:
            entry = {
                "type": "render_status",
                "clip_id": int(m_render.group(1)),
                "status": m_render.group(2).strip(),
                "ts": timestamp,
            }
        else:
            m = re.match(r'^PROGRESS\|(\d+)\|(.+)$', message)
            if m:
                parts = m.group(2).split('|')
                msg_text = parts[0]
                eta_val = int(parts[1]) if len(parts) > 1 else None
                entry = {
                    "type": "progress",
                    "percent": int(m.group(1)),
                    "message": f"[{timestamp}] {msg_text.strip()}",
                    "ts": timestamp,
                    "eta": eta_val
                }
            else:
                entry = {
                    "type": "status",
                    "message": f"[{timestamp}] {message.strip()}",
                    "ts": timestamp,
                }
        self._entries.append(entry)
        print(f"[{timestamp}] {message}")

    def error(self, message: str):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        entry = {
            "type": "error",
            "message": f"[{timestamp}] ERROR: {message.strip()}",
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
