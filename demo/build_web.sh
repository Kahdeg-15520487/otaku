#!/usr/bin/env bash
# Assemble the deployable web demo: the REAL page (otaku/web/static, byte
# for byte) plus the demo's own files, with one script tag injected into
# a copy of index.html — the product's file is never touched.
#
#   demo/build_web.sh [target-dir]     (default dist/demo-web)
#
# The two demos build alike: demo/web here, demo/terminal through
# demo/build_terminal.sh, each into its own dist/demo-* folder.
# Deploying is copying the target into the otaku.sh Worker's assets
# (public/demo/) and running that repo's `wrangler deploy` — e.g.
#
#   demo/build_web.sh path/to/otaku-sh/public/demo
set -euo pipefail
cd "$(dirname "$0")/.."

TARGET="${1:-dist/demo-web}"
STATIC="otaku/web/static"

[ -f demo/web/fixtures/river.json ] || {
  echo "demo/web/fixtures/ is missing — run: conda run -n otaku python demo/capture_fixtures_web.py" >&2
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
