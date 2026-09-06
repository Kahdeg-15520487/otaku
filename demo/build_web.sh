#!/usr/bin/env bash
# Assemble the deployable web demo: the REAL page (otaku/web/static, byte
# for byte) plus the demo's own files, with one script tag injected into
# a copy of index.html — the product's file is never touched.
#
#   demo/build_web.sh <target-dir>
#
# One PIECE of the demos' one procedure, which is the site repo's
# demos/build.sh: that regenerates the fixtures (demo/capture_fixtures_web.py,
# committed here so a payload change reviews as a diff), runs this and
# demo/build_terminal.sh into the site's own folders, and decorates. Nothing
# is built inside this repo — the target is always named. It is plain static
# files: any static host serves it as it is, and whatever a site lays over
# the page — its own headers, its own scripts — is that site's to add.
set -euo pipefail
cd "$(dirname "$0")/.."

TARGET="${1:?usage: demo/build_web.sh <target-dir>}"
STATIC="otaku/web/static"

[ -f demo/web/fixtures/river.json ] || {
  echo "demo/web/fixtures/ is missing — run demo/capture_fixtures_web.py with the otaku environment's python" >&2
  exit 1
}

rm -rf "$TARGET"
mkdir -p "$TARGET"
cp -R "$STATIC/." "$TARGET/"
cp demo/web/demo.js demo/web/store.js demo/web/script.js "$TARGET/"
cp demo/web/custom.css "$TARGET/custom.css"
cp -R demo/web/fixtures "$TARGET/fixtures"

# The one delta from the product's page: the demo module, loaded before
# app.js so the fetch patch is installed first — and the tab named as
# what it is.
python3 - "$TARGET/index.html" <<'EOF'
import sys
from pathlib import Path

page = Path(sys.argv[1])
text = page.read_text()
tag = '<script type="module" src="app.js"></script>'
assert text.count(tag) == 1, "index.html changed shape — update build_web.sh"
text = text.replace(tag, f'<script type="module" src="demo.js"></script>\n{tag}')
text = text.replace("<title>otaku</title>", "<title>otaku web demo</title>")
page.write_text(text)
EOF

echo "built $TARGET ($(find "$TARGET" -type f | wc -l | tr -d ' ') files)"
