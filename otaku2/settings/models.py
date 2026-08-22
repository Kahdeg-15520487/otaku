"""Per-model inference parameters: models.toml, written by /set parameter."""

import tomllib
from pathlib import Path

from otaku2.formatting import toml_key, toml_scalar
from otaku2.settings import write_atomic

_HEADER = [
    "# Per-model inference parameters, written by /set parameter.",
    "# Keyed by bare model name.",
    "",
]


def load(path: Path) -> dict[str, dict[str, object]]:
    """Every model's saved parameters. Best effort: a missing or
    malformed file yields no overrides."""
    if not path.exists():
        return {}
    try:
        raw = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return {str(name): dict(entry) for name, entry in raw.items() if isinstance(entry, dict)}


def save_parameters(path: Path, model: str, parameters: dict[str, object]) -> None:
    """Replace one model's saved parameters (empty = remove its entry),
    keeping every other model's. Raises ValueError on an unreadable file
    rather than silently dropping the other models' settings."""
    data: dict[str, dict[str, object]] = {}
    if path.exists():
        try:
            raw = tomllib.loads(path.read_text())
        except (OSError, tomllib.TOMLDecodeError) as e:
            raise ValueError(f"{path} is unreadable ({e}); fix or move it") from e
        data = {str(name): dict(entry) for name, entry in raw.items() if isinstance(entry, dict)}
    if parameters:
        data[model] = dict(parameters)
    else:
        data.pop(model, None)
    lines = list(_HEADER)
    for name in sorted(data):
        lines.append(f"[{toml_key(name)}]")
        lines += [f"{toml_key(k)} = {toml_scalar(v)}" for k, v in sorted(data[name].items())]
        lines.append("")
    write_atomic(path, "\n".join(lines))
