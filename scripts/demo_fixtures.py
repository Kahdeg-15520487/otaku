#!/usr/bin/env python
"""Regenerate demo/fixtures/ from a real session over the shipped
sample story.

The session is opened over a THROWAWAY state dir this script creates and
deletes — never anyone's real ~/.otaku — so a regeneration can never
capture personal library content into a committed file. The captured
payloads are exactly what `otaku/web/api.py` serves, so the demo's seed
is the product's own truth; any path the throwaway dir leaks into a
payload is scrubbed before writing.

Run from the repo root:  conda run -n otaku python scripts/demo_fixtures.py
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from otaku.backend import launch
from otaku.backend.api import stories as api_stories
from otaku.web import api as web_api

FIXTURES = Path(__file__).resolve().parent.parent / "demo" / "fixtures"


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="otaku-demo-fixtures-") as root:
        session = launch.open_session(root)
        try:
            # A fresh launch seeds the sample but starts detached; the
            # demo opens ON the story, so land at its last message.
            if session.story_id is None:
                listing = api_stories.listing(session)
                assert listing, "the sample story was not seeded"
                messages = api_stories.messages_of(session, listing[0].id)
                api_stories.land(session, listing[0].id, messages[-1].id, "resume")

            row = next(r for r in web_api.stories(session) if r["open"])
            fixtures = {
                "syntax": web_api.syntax(),
                "settings": web_api.settings(session),
                "river": {
                    "facts": web_api.facts(session),
                    "story": row,
                    # The story WHOLE — the one read the dossier makes,
                    # so the demo seeds from the shape the page reads.
                    "opened": web_api.story(session, session.story_id),
                    "context": web_api.context(session),
                },
            }
        finally:
            session.close()

        FIXTURES.mkdir(parents=True, exist_ok=True)
        for name, payload in fixtures.items():
            text = json.dumps(payload, ensure_ascii=False, indent=1)
            # The throwaway root must not reach a committed file — nor
            # would any real path belong in a payload the page seeds from.
            scrubbed = text.replace(root, "~/.otaku").replace(str(Path.home()), "~")
            path = FIXTURES / f"{name}.json"
            path.write_text(scrubbed + "\n", encoding="utf-8")
            print(f"wrote {path} ({len(scrubbed):,} chars)")


if __name__ == "__main__":
    main()
