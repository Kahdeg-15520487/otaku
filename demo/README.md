# The demos

Two demos, one per frontend, built alike: `web/` and `terminal/` hold
the committed sources, the scripts beside them assemble the discardable
builds. Every script starts with a verb and ends with the frontend it
serves; the mechanics live in each script's own header.

- **`build_web.sh`** → `dist/demo-web`. The real page
  (`otaku/web/static`, byte for byte) plus the demo's own files, one
  script tag injected.
- **`build_terminal.sh`** → `dist/demo-terminal`. The real terminal
  frontend on Pyodide: the otaku wheel, the runtime, xterm.js — all
  self-hosted static files.
- **`capture_fixtures_web.py`** → `demo/web/fixtures/`, committed. Run
  it whenever the answers the page would receive change — a field added
  or dropped in `otaku/web/api.py`'s payloads, a sample story edited,
  the assembler's context preview reshaped — and commit the diff: the
  fixtures are recordings of the product's real answers, so the diff IS
  the review of what the demo will now claim.
- **`serve_terminal.py`** — serves `dist/demo-terminal` locally with the
  two cross-origin isolation headers SharedArrayBuffer requires (in
  deployment the built `_headers` file carries them). There is no
  `serve_web`: the web demo is plain static files, so any static server
  works — `python3 -m http.server -d dist/demo-web`.

The terminal demo's offline check is `demo/terminal/smoke.mjs` (a
scripted session on Pyodide under Node); its header says how to run it.
