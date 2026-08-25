/* The shared command table, as the page holds it — the LANGUAGE half of
   `backend.commands`: which row a typed line names, where its argument
   starts, what counts as a command at all. Dispatch — which screen a
   token opens, what a click runs — is `commands.js`, exactly as the
   backend splits its declaration from the terminal's bindings.

   A leaf on purpose: the composer's menu, the transcript's highlighting
   and the help sheet read the language without depending on any screen.
   Loaded at boot from /api/read/commands, and again whenever a
   restarted otaku comes back — the table is the backend's, and the page
   never keeps a stale copy of a language. */

// The whole payload once, and the lookups built from it.
let table = null;
let specs = new Map();
let answerable = new Set();
let tokens = [];

export function load(loaded) {
  table = loaded;
  specs = new Map(table.rows.map((row) => [row.token, row]));
  answerable = new Set(table.answers);
  // Every slash word the app answers to, so what counts as a command is
  // the table's answer and never a guess from the slash: `/me` is one,
  // `and/or` is not.
  tokens = table.rows
    .flatMap((row) => row.token.split(" "))
    .filter((word) => /^\/[a-z]+$/.test(word));
}

/** Every row, in the table's own order — the completion menu's and the
    help sheet's. */
export function allSpecs() {
  return [...specs.values()];
}

/** What each group is called, for the help sheet: what the page SAYS
    about the language is the table's, never its own. */
export function groups() {
  return table?.groups ?? {};
}

/** The row that is not a command — the prose explainer the help sheet
    opens the playing group with. */
export function prose() {
  return table?.prose ?? null;
}

/** The row a typed line names — the longest match wins, so "/set think
    medium" finds the "/set think" row. The page needs its own answer
    because it must know BEFORE posting whether a slash line is story or
    a command; `backend.commands.find` holds the same rule. */
export function specFor(line) {
  const words = line.trim().split(/\s+/);
  for (const depth of [2, 1]) {
    const spec = specs.get(words.slice(0, depth).join(" "));
    if (spec) return spec;
  }
  return null;
}

/** Whether a typed line is a command rather than story. A direction
    (/me, /you, /ooc) is story: the table says which is which, so the
    slash alone never decides. */
export function isCommand(line) {
  return line.startsWith("/") && specFor(line)?.kind !== "syntax";
}

/** Whether the BACKEND answers this token with a sentence — the shared
    table's `answers`, which is what divides `/model ollama/x` (posted)
    from bare `/model` (a screen). */
export function answered(token) {
  return answerable.has(token);
}

/** Whether one word of a played line is the language's own — the
    transcript's highlighting asks per word. */
export function isToken(word) {
  return tokens.includes(word);
}

/** Everything after the token, verbatim from the first non-space
    character — the page's copy of `backend.commands.raw_argument`,
    cited: a screen and an operation must read a line the same way, and
    this is the one rule the language barrier forces us to write twice. */
export function rawArgument(line, spec) {
  if (!spec) return "";
  let rest = line;
  for (const _ of spec.token.split(" ")) {
    rest = rest.trimStart().split(" ").slice(1).join(" ");
  }
  return rest.trimStart();
}
