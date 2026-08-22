"""The full-screen surfaces: the model picker, the story browser, and
the lore browser over the shared `ListScreen` base. ONE ownership rule
for all three: reads are free, and every action the user confirms is
EXECUTED inside the screen through `backend.api` — a screen returns the
line to print (or None), never work for the caller to finish."""
