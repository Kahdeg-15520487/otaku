"""The configuration files under configs/, each function handed the plain
Path it reads or writes — this package resolves no locations itself.

`config` owns config.toml (user-owned, edited only by migrations),
`providers` the providers.toml sections and their `ProviderConfig` type
(provider settings are settings), `state` what the app remembers
between sessions, `models` the per-model parameter overrides,
`prompts` the model-facing templates, and `migrations` the convergent
launch-time edits. The write helpers every sibling shares live right
here. Api-key sealing is NOT here: it is encryption's second plane
(`encryption.keys`), reached by the backend — this package touches no
key material.
"""

from pathlib import Path

# Written config lines align their comments to one column, so the values
# read as a column instead of a wall of prose.
_COMMENT_COLUMN = 30


def row(setting: str, comment: str) -> str:
    """One config line with its comment aligned to the shared column. A
    setting longer than the column still gets two spaces before the #."""
    if not comment:
        return setting
    if len(setting) < _COMMENT_COLUMN:
        return f"{setting:<{_COMMENT_COLUMN}}# {comment}"
    return f"{setting}  # {comment}"


def write_atomic(path: Path, text: str) -> None:
    """Write via tmp + rename, so a kill mid-write can never truncate."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)
