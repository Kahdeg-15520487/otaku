"""The system log: the app's account of the work nobody watched.

`logs/system-YYYYMMDD.log`, one `<timestamp> <action>` line per action —
the lore worker's whole account of itself (scenes closed, rollups
rebuilt, retries, failures, warm-ups), and the app's administrative
moments: the schema migration, the daily database backup, an `otaku
update` run. The log exists to make unattended work transparent, so it
records work done (and declined, with the reason), never scheduling
noise.

CONTENT-FREE by contract: actions carry ids and counts, never prose —
titles, summaries, and message text are sealed in the database, and a
plaintext log must not leak what the cipher protects. Anything new logged
here follows that rule. Best-effort: a logging failure warns once and never
blocks anything.
"""

import sys
import threading
from datetime import datetime

from otaku.logs.daily import DailyLog
from otaku.paths import Paths


class SystemLog(DailyLog):
    _prefix = "system-"
    _suffix = ".log"

    def __init__(self, paths: Paths) -> None:
        super().__init__(paths)
        self._lock = threading.Lock()  # appends come from worker and REPL threads
        self._warned = False

    def record(self, action: str) -> None:
        """Append one timestamped action line. Never raises — the log is an
        account, not a dependency."""
        now = datetime.now().astimezone()
        line = f"{now.isoformat(timespec='seconds')} {action}\n"
        try:
            with self._lock:
                path = self.get_path(now.strftime("%Y%m%d"))
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as f:
                    f.write(line)
        except OSError as e:
            if not self._warned:
                self._warned = True
                print(f"otaku: system logging failed: {e}", file=sys.stderr)
