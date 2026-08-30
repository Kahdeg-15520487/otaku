"""The full-screen surfaces: the model picker, the story browser, and
the story dossier the browser (and /lore, /cast) drills into — all over
the shared `ListScreen` base — with `_meminfo` beside them, the
machine's own memory numbers for the picker's RAM gauge. ONE ownership
rule for all of them: reads are free, and every action the user
confirms is EXECUTED inside the screen through `backend.api` — a screen
returns the line to print (or None), never work for the caller to
finish."""
