"""Day-rotated logs under one directory, handed in as a plain Path.

One base and three logs, one class each in this one module: `RequestLog`
(every model-bound request body, sealed with the cipher the caller hands
in — the session's, so the log protects exactly what the database
protects), `SystemLog` (the app's account of unattended work;
CONTENT-FREE by contract: ids and counts, never prose), and `ErrorLog`
(every contained crash's traceback; frames and messages only, NEVER
locals — this file sits in plain text beside a possibly-encrypted
database). All best-effort: a logging failure warns on stderr once and
never blocks anything — the one sanctioned stderr voice below cli. The
view functions at the bottom render the logs for `otaku logs`.
"""

import base64
import json
import re
import sys
import threading
import traceback
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import ClassVar

from otaku2.encryption import Cipher, PlainCipher
from otaku2.formatting import printable

__all__ = ["DailyLog", "Entry", "ErrorLog", "RequestLog", "SystemLog"]


class DailyLog:
    """The base every log shares: `<prefix>YYYYMMDD<suffix>` files, which
    days exist, and the one locked mkdir-append-warn write body."""

    _prefix: ClassVar[str]
    _suffix: ClassVar[str]

    def __init__(self, directory: Path) -> None:
        self._dir = directory
        self._lock = threading.Lock()  # appends come from worker and REPL threads
        self._warned = False

    def get_days(self) -> list[tuple[str, int]]:
        """The available log days as (YYYYMMDD, file size), oldest first."""
        if not self._dir.exists():
            return []
        out: list[tuple[str, int]] = []
        for path in sorted(self._dir.glob(f"{self._prefix}????????{self._suffix}")):
            out.append((path.name[len(self._prefix) : -len(self._suffix)], path.stat().st_size))
        return out

    def get_path(self, day: str) -> Path:
        return self._dir / f"{self._prefix}{day}{self._suffix}"

    def _append(self, text: str) -> Path:
        """Append `text` to today's file under the lock; warn on stderr
        once per instance when the write fails. Returns the day's path."""
        path = self.get_path(datetime.now().astimezone().strftime("%Y%m%d"))
        try:
            with self._lock:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as f:
                    f.write(text)
        except OSError as e:
            if not self._warned:
                self._warned = True
                print(f"otaku: logging failed: {e}", file=sys.stderr)
        return path


class ErrorLog(DailyLog):
    _prefix = "error-"
    _suffix = ".log"

    def record(self, context: str, exc: BaseException) -> Path:
        """Append one crash: a `=== <timestamp> <context>` header and the
        traceback. Returns the day's file (for the on-screen notice);
        never raises."""
        now = datetime.now().astimezone()
        header = f"=== {now.isoformat(timespec='seconds')} {context}\n"
        body = "".join(traceback.format_exception(exc))
        return self._append(header + body + "\n")


class SystemLog(DailyLog):
    _prefix = "system-"
    _suffix = ".log"

    def record(self, action: str) -> None:
        """Append one timestamped action line — work done or declined
        with the reason, never scheduling noise. Never raises."""
        now = datetime.now().astimezone()
        self._append(f"{now.isoformat(timespec='seconds')} {action}\n")


@dataclass(frozen=True)
class Entry:
    ts: str
    provider: str
    purpose: str
    body: dict[str, object] | None  # None when the body cannot be read back


class RequestLog(DailyLog):
    _prefix = "requests-"
    _suffix = ".jsonl"

    def __init__(self, directory: Path, cipher: Cipher) -> None:
        """The envelope is plaintext; the body is sealed with `cipher`
        (readable inline JSON under the plain cipher)."""
        super().__init__(directory)
        self._cipher = cipher

    def record(self, provider: str, purpose: str, body: dict[str, object]) -> None:
        """Append one request. Best-effort; never fails the request."""
        now = datetime.now().astimezone()
        entry: dict[str, object] = {
            "ts": now.isoformat(timespec="seconds"),
            "provider": provider,
            "purpose": purpose,
        }
        if isinstance(self._cipher, PlainCipher):
            entry["body"] = body
        else:
            sealed = self._cipher.seal(json.dumps(body, ensure_ascii=False).encode("utf-8"))
            entry["body_sealed"] = base64.b64encode(sealed).decode()
        self._append(json.dumps(entry, ensure_ascii=False) + "\n")

    def read(self, day: str) -> Iterator[Entry]:
        """The day's entries in order; a body the cipher cannot open (or
        a corrupt line) yields body=None rather than failing the day."""
        for line in self.get_path(day).read_text(encoding="utf-8").splitlines():
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                yield Entry(ts="?", provider="?", purpose="?", body=None)
                continue
            yield Entry(
                ts=str(raw.get("ts", "?")),
                provider=str(raw.get("provider", "?")),
                purpose=str(raw.get("purpose", "?")),
                body=self._get_body(raw),
            )

    def _get_body(self, raw: dict[str, object]) -> dict[str, object] | None:
        """One raw JSON line's body, opened with the session cipher —
        None when it cannot be read back (wrong key, corrupt line)."""
        body = raw.get("body")
        if isinstance(body, dict):
            return body
        sealed = raw.get("body_sealed")
        if not isinstance(sealed, str):
            return None
        try:
            plain = self._cipher.unseal(base64.b64decode(sealed))
            parsed = json.loads(plain.decode("utf-8"))
        except Exception:
            return None
        return parsed if isinstance(parsed, dict) else None


# ---------- rendering for `otaku logs` ----------


def resolve_day(day: str) -> str | None:
    """A DAY argument as the logs name their files (YYYYMMDD); the dashed
    form accepted too. None when it is neither."""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        return day.replace("-", "")
    if re.fullmatch(r"\d{8}", day):
        return day
    return None


def dashed(stamp: str) -> str:
    """YYYYMMDD as YYYY-MM-DD — the human way the listings print."""
    return f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"


def day_rows(days: list[tuple[str, int]]) -> list[str]:
    """The `--list` rows: one dashed day and its size per line."""
    return [f"{dashed(name)}  {size:>10,} B" for name, size in days]


def render_requests(log: RequestLog, stamp: str) -> Iterator[str]:
    """One day's request log as pager text: per entry a header row, the
    non-message fields as one JSON row, then each message — display goes
    through `formatting.printable`; the log itself stores every byte."""
    for entry in log.read(stamp):
        yield f"=== {entry.ts}  {entry.provider}  [{entry.purpose}]\n"
        if entry.body is None:
            yield "  <unreadable: wrong key or corrupted>\n\n"
            continue
        meta = {k: v for k, v in entry.body.items() if k != "messages"}
        yield f"  {printable(json.dumps(meta, ensure_ascii=False))}\n"
        messages = entry.body.get("messages")
        if isinstance(messages, list):
            for message in messages:
                if isinstance(message, dict):
                    yield f"  [{message.get('role')}] {printable(str(message.get('content')))}\n"
        yield "\n"
