"""Calling the user back to the screen — the platform's own player, and
the terminal's own bell.

`/set notification` decides WHETHER a landed reply rings; this is the
how. No dependency for it: every platform ships a player, and a machine
without one still has `BELL` — which is why this lives with the medium
rather than beside its caller. The bell is the honest fallback rather
than a lesser one: the emulator is what turns it into a beep, a flash,
or a desktop notification, so the last word belongs to the terminal
either way.

Which sound is `config.toml`'s `notification_sound`: "default" for the
platform's own task-finished sound, or a path. A path that is not there
to play rings the bell too — audible and wrong beats silent and wrong,
because silence reads as a broken feature rather than a bad setting.

Never waits: a sound is a second of audio the prompt has no reason to
sit through, so the player is spawned and let go.
"""

import shutil
import subprocess
import sys
from pathlib import Path

from otaku.terminal import tty

DEFAULT = "default"  # the config value meaning "the platform's own"

# macOS answers both questions with one fixed path each. Every other
# unix is a question of which audio stack is installed, so its players
# are tried in order — `aplay` last, reading WAV alone.
_MACOS_PLAYERS = (["afplay"],)
_MACOS_SOUND = "/System/Library/Sounds/Glass.aiff"
_UNIX_PLAYERS = (["paplay"], ["aplay", "-q"])
_UNIX_SOUND = "/usr/share/sounds/freedesktop/stereo/complete.oga"


def ring(sound: str) -> None:
    """Ring once for a reply that landed — `sound` as config.toml spells
    it. Never raises and never waits."""
    command = _command(sound)
    if command is None:
        _bell()
        return
    try:
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        _bell()


def _command(sound: str) -> list[str] | None:
    """The player command for `sound`, or None where this machine cannot
    play it — an absent file or no player on the PATH. Both are decided
    BEFORE spawning, because a player that is never waited on cannot
    report its own failure."""
    path = _sound_file(sound)
    if path is None:
        return None
    for player in _MACOS_PLAYERS if _macos() else _UNIX_PLAYERS:
        binary = shutil.which(player[0])
        if binary is not None:
            return [binary, *player[1:], str(path)]
    return None


def _sound_file(sound: str) -> Path | None:
    """The file to play: the platform's own for "default", else the
    configured path — None when it is not a readable file."""
    name = (_MACOS_SOUND if _macos() else _UNIX_SOUND) if sound == DEFAULT else sound
    path = Path(name).expanduser()
    try:
        return path if path.is_file() else None
    except OSError:
        return None  # a name the filesystem will not even look up


def _macos() -> bool:
    return sys.platform == "darwin"


def _bell() -> None:
    """BEL to the terminal, which decides what it means."""
    try:
        sys.stdout.write(tty.BELL)
        sys.stdout.flush()
    except (OSError, ValueError):
        pass
