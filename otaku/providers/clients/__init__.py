"""One module per native engine; `CLIENTS` in the registry maps names to
these classes in the panel's canonical order."""

import json
from pathlib import Path
from typing import Any


def read_home_json(relative: str) -> dict[str, Any]:
    """A JSON object at `~/<relative>`, or {} on any failure — how a local
    app's own config file is consulted at autoconfigure time."""
    try:
        parsed = json.loads((Path.home() / relative).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
