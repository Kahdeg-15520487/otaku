/* Dates and numbers as the page spells them — the row, preview and
   report spellings the screens share. Nothing here knows what otaku is. */

/** The preview's fuller date: the weekday earns its place because a
    story is remembered as "that Saturday", not as a number. */
export function when(iso) {
  const d = new Date(iso);
  const pad = (n) => String(n).padStart(2, "0");
  const day = d.toLocaleDateString("en-US", { weekday: "short" });
  return `${day} ${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function ago(iso) {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  for (const [unit, size] of [["d", 86400], ["h", 3600], ["m", 60]]) {
    if (seconds >= size) return `${Math.floor(seconds / size)}${unit} ago`;
  }
  return "just now";
}

/** The same distance in a column's width: "2h", "3d", "now". */
export function since(iso) {
  const worded = ago(iso);
  return worded === "just now" ? "now" : worded.replace(" ago", "");
}

/** One line of a text, as much as the limit holds — for a row that cuts
    with an ellipsis rather than wrapping. */
export function excerpt(text, limit = 120) {
  const line = text.replace(/\s+/g, " ").trim();
  return line.length > limit ? `${line.slice(0, limit)}…` : line;
}

/* How wide a story's name is written, anywhere on the page. The backend
   cuts to the same number inside its own sentences
   (`backend.api.stories.LABEL_WIDTH`), so a name reads the same length
   whether the page drew it or otaku said it. */
const LABEL_WIDTH = 50;
const _FORK_NUMBER = / - \d+$/;

/** A story's name, cut for one line — the RULE `formatting.truncate_label`
    holds for the terminal, copied here because the two languages cannot
    share a function: flattened, at most `limit` characters, and a trailing
    fork number (" - 2") survives the cut, because it is the only thing
    telling two copies of one story apart and it sits exactly where the cut
    would land. */
export function label(text, limit = LABEL_WIDTH) {
  const flat = String(text ?? "").replace(/\s+/g, " ").trim();
  const cut = (line, n) => (line.length <= n ? line : n <= 1 ? line.slice(0, n) : `${line.slice(0, n - 1)}…`);
  const number = flat.match(_FORK_NUMBER);
  if (!number) return cut(flat, limit);
  return `${cut(flat.slice(0, number.index), limit - number[0].length)}${number[0]}`;
}

/** A number as the reports write them: grouped, so a token count can be
    read at a glance. The terminal's own `:,` in a page's spelling. */
export function count(n) {
  return n.toLocaleString("en-US");
}
