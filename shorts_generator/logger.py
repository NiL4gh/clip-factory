import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import sys

# Write the AI-debug logs to the Drive-persistent location so they survive the
# Colab runtime being recycled (these exist so an AI can diagnose past runs).
# Fall back to the repo's work/logs if config can't be imported.
try:
    from .config import LOGS_DIR as _LOGS_DIR
    LOG_DIR = Path(_LOGS_DIR)
except Exception:
    LOG_DIR = Path(__file__).parent.parent / 'work' / 'logs'
LOG_DIR.mkdir(parents=True, exist_ok=True)

def safe_print(message: str) -> None:
    try:
        print(message)
    except UnicodeEncodeError:
        try:
            encoding = sys.stdout.encoding or 'utf-8'
            encoded_msg = message.encode(encoding, errors='replace').decode(encoding)
            print(encoded_msg)
        except Exception:
            try:
                print(message.encode('ascii', errors='replace').decode('ascii'))
            except Exception:
                pass

# ── Preserve existing UIStreamLogger for websocket compat ──
class UIStreamLogger:
    """Original websocket logger - DO NOT REMOVE"""
    def __init__(self):
        self._entries = []
        self._last_read_idx = 0
        self.clients = []

    def register(self, ws):
        self.clients.append(ws)

    def log(self, message: str, level: str = "info"):
        import asyncio
        timestamp = datetime.now().strftime("%H:%M:%S")
        safe_print(f"[{timestamp}] {message}")

        # Build a typed payload first — the WebSocket polling loop in main.py reads
        # _entries directly and sends whatever is there, so the entry itself must carry
        # the right type. Previously this always wrote type="status", which meant
        # PROGRESS| messages were never routed correctly on the frontend.
        msg = message.strip()
        if msg.startswith("PROGRESS|"):
            parts = msg.split("|")
            percent = int(parts[1]) if len(parts) > 1 and parts[1].strip().lstrip("-").isdigit() else 0
            rest = parts[2:]
            eta = None
            if len(rest) > 1 and rest[-1].strip().isdigit():
                eta = int(rest[-1].strip())
                rest = rest[:-1]
            payload = {
                "type": "progress",
                "percent": percent,
                "message": "|".join(rest),
                "eta": eta,
            }
        elif level == "error":
            payload = {"type": "error", "message": f"[{timestamp}] {msg}", "time": datetime.utcnow().isoformat()}
        else:
            payload = {"type": "status", "level": level,
                       "message": f"[{timestamp}] {msg}", "ts": timestamp,
                       "time": datetime.utcnow().isoformat()}

        self._entries.append(payload)

        for ws in self.clients[:]:
            try:
                asyncio.create_task(ws.send_json(payload))
            except:
                self.clients.remove(ws)

    def error(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = {
            "type": "error",
            "message": f"[{timestamp}] ERROR: {message.strip()}",
            "ts": timestamp,
        }
        self._entries.append(entry)
        safe_print(f"[{timestamp}] ERROR: {message}")
        
        self.log(message, "error")

    def success(self, msg):
        self.log(msg, "success")

    def info(self, msg):
        self.log(msg, "info")

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

# ── NEW: AppLogger with human-readable summaries ──
class AppLogger:
    """Structured logger that writes both machine-readable JSONL and human-friendly text summaries."""
    def __init__(self, session_id: str, video_title: str = ""):
        self.session_id = session_id
        self.logger = logging.getLogger(f"AppLogger.{session_id}")
        self.ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        if video_title:
            safe = "".join(c for c in video_title if c.isalnum() or c in " _-")[:60].strip()
        else:
            safe = session_id
        log_subdir = LOG_DIR / safe
        log_subdir.mkdir(parents=True, exist_ok=True)
        self.jsonl_path = log_subdir / f'session log {safe}.jsonl'
        self.text_path  = log_subdir / f'llm log {safe}.log'

        self._file = open(self.text_path, 'a', encoding='utf-8')
        self._entries: List[Dict[str, Any]] = []
        self._write_header()

    def _write_header(self):
        self._file.write(f"\n{'='*60}\n")
        self._file.write(f"Session: {self.session_id} | Started: {datetime.now().strftime('%H:%M:%S')}\n")
        self._file.write(f"{'='*60}\n\n")
        self._file.flush()

    def _write_jsonl(self, entry: Dict[str, Any]) -> None:
        self._entries.append(entry)
        with open(self.jsonl_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')

    def _human_time(self) -> str:
        return datetime.now().strftime('%H:%M:%S')

    def _write_human(self, lines: List[str]) -> None:
        for line in lines:
            self._file.write(f"[{self._human_time()}] {line}\n")
        self._file.write("\n")
        self._file.flush()

    # ── Public API: App Events ──
    def log_app_event(self, stage: str, status: str, details: Optional[Dict] = None, error: Optional[str] = None) -> None:
        self.log_app(stage, status, details, error)

    def log_app(self, stage: str, status: str, details: Optional[Dict] = None, error: Optional[str] = None) -> None:
        entry = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'type': 'app',
            'stage': stage,
            'status': status,
            'details': details or {},
            'error': error,
            'session_id': self.session_id
        }
        self._write_jsonl(entry)
        
        # Human-readable summary
        human_lines = [f"📱 APP  | {stage.upper()} → {status.upper()}"]
        if details:
            for k, v in details.items():
                human_lines.append(f"       • {k}: {v}")
        if error:
            human_lines.append(f"       ❌ ERROR: {error}")
        self._write_human(human_lines)
        
        # Also broadcast to websocket
        ui_logger.log(f"[{stage}] {status}" + (f" | ERROR: {error}" if error else ""), 
                     "error" if error else "info")

    # ── Public API: LLM Events ──
    def log_llm(self, model: str, prompt: str, response: str, reasoning: Optional[str] = None,
                latency_ms: Optional[float] = None, error: Optional[str] = None) -> None:
        entry = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'type': 'llm',
            'model': model,
            'prompt_preview': prompt[:600] + '...' if len(prompt) > 600 else prompt,
            'full_prompt': prompt,
            'response_preview': response[:600] + '...' if len(response) > 600 else response,
            'full_response': response,
            'reasoning': reasoning,
            'latency_ms': latency_ms,
            'error': error,
            'session_id': self.session_id
        }
        self._write_jsonl(entry)
        
        human_lines = [f"🤖 LLM  | Model: {model} | Time: {latency_ms:.0f}ms" if latency_ms else f"🤖 LLM  | Model: {model}"]
        if reasoning:
            human_lines.append(f"       💭 Reasoning:")
            for line in reasoning.split('\n')[:8]:  # first 8 lines
                human_lines.append(f"         {line}")
        if error:
            human_lines.append(f"       ❌ FAILED: {error}")
        else:
            # Extract clip count if present
            if '"clips"' in response or '"clip"' in response:
                human_lines.append(f"       ✅ Extracted clips from response")
            human_lines.append(f"       📄 Response preview: {response[:120]}...")
        self._write_human(human_lines)
        
        ui_logger.log(f"[LLM:{model}] {'ERROR' if error else 'OK'} in {latency_ms:.0f}ms" if latency_ms else f"[LLM:{model}] {'ERROR' if error else 'OK'}", 
                     "error" if error else "success")

    # ── Public API: FFmpeg Events ──
    def log_ffmpeg(self, command: str, return_code: int, stdout: str, stderr: str,
                   duration_sec: Optional[float] = None) -> None:
        entry = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'type': 'ffmpeg',
            'command': command[:250],
            'return_code': return_code,
            'stdout_tail': stdout[-400:] if stdout else None,
            'stderr_tail': stderr[-800:] if stderr else None,
            'duration_sec': duration_sec,
            'session_id': self.session_id
        }
        self._write_jsonl(entry)
        
        status = "✅ SUCCESS" if return_code == 0 else "❌ FAILED"
        human_lines = [
            f"🎬 FFMPEG | {status} | Exit code: {return_code}",
            f"       ⏱️  Duration: {duration_sec:.2f}s" if duration_sec else "       ⏱️  Duration: unknown",
            f"       📝 Command: {command[:100]}..."
        ]
        if return_code != 0 and stderr:
            human_lines.append(f"       ⚠️  Error: {stderr[-200:]}")
        self._write_human(human_lines)
        
        ui_logger.log(f"[FFMPEG] {status} (code:{return_code})", 
                     "error" if return_code != 0 else "info")

    def get_entries(self, log_type: Optional[str] = None, limit: int = 200, filter_type: Optional[str] = None) -> List[Dict[str, Any]]:
        target_type = log_type or filter_type
        filtered = [e for e in self._entries if not target_type or e.get('type') == target_type]
        return filtered[-limit:]

    def get_human_log(self) -> str:
        """Return the human-readable text log for display."""
        self._file.flush()
        try:
            with open(self.text_path, 'r', encoding='utf-8') as f:
                return f.read()
        except:
            return "Log file not available."

_loggers: Dict[str, AppLogger] = {}

def get_logger(session_id: str, video_title: str = "") -> AppLogger:
    if session_id not in _loggers:
        _loggers[session_id] = AppLogger(session_id, video_title=video_title)
    return _loggers[session_id]
