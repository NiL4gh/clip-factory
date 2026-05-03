import queue
import datetime

class UIStreamLogger:
    def __init__(self):
        self.q = queue.Queue()
        self.full_log = ""

    def log(self, message):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        formatted = f"[{timestamp}] {message}"
        print(formatted)
        self.q.put(formatted)
        self.full_log += formatted + "\n"

    def get_new_logs(self):
        new_lines = []
        while not self.q.empty():
            new_lines.append(self.q.get())
        if new_lines:
            return "\n".join(new_lines)
        return None

    def get_full_log(self):
        return self.full_log

    def clear(self):
        self.full_log = ""
        while not self.q.empty():
            try:
                self.q.get_nowait()
            except queue.Empty:
                break

ui_logger = UIStreamLogger()
