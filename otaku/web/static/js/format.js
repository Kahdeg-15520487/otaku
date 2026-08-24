/* Dates and numbers as the page spells them — the row, preview and
   report spellings the screens share. Nothing here knows what otaku is. */

/** A row's date: the month, the day and the clock, which is what tells
    two plays of the same story apart at a glance. */
export function stamp(iso) {
  const d = new Date(iso);
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

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

/** One line of a text, as much as the limit holds — for a row that cuts
    with an ellipsis rather than wrapping. */
export function excerpt(text, limit = 120) {
  const line = text.replace(/\s+/g, " ").trim();
  return line.length > limit ? `${line.slice(0, limit)}…` : line;
}

/** A number as the reports write them: grouped, so a token count can be
    read at a glance. The terminal's own `:,` in a page's spelling. */
export function count(n) {
  return n.toLocaleString("en-US");
}
