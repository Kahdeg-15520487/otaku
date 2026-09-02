/* Making and finding elements. Nothing here knows what otaku is. */

export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

export function element(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}

export function span(className, text) {
  return element("span", className, text);
}

export function row(...parts) {
  const button = element("button", "otk-row");
  button.type = "button";
  button.setAttribute("role", "option");
  button.append(...parts);
  return button;
}

/** One verb of an action row. `onclick` arrives already answered-for:
    this module knows nothing about screens, guards included. */
export function actionButton(label, { kind = "", off = false, onclick } = {}) {
  const button = element("button", kind ? `otk-btn ${kind}` : "otk-btn", label);
  button.type = "button";
  button.disabled = off;
  if (onclick) button.onclick = onclick;
  return button;
}

// ---------- textareas that size to their text ----------

// Safari has no `field-sizing: content` yet; where it exists this stays
// out of the way entirely.
const NEEDS_AUTOSIZE = !CSS.supports("field-sizing", "content");

export function autosize(field) {
  if (!NEEDS_AUTOSIZE) return;
  field.style.height = "auto";
  field.style.height = `${field.scrollHeight}px`;
}

/* Setting .value fires no input event, so every programmatic write says
   so itself — a command prefilling the composer, an editor opening on
   existing text. Without this the box opens one line tall with the text
   scrolled out of sight. */
export function setValue(field, text) {
  field.value = text;
  autosize(field);
}

export function watchTextareas() {
  if (!NEEDS_AUTOSIZE) return;
  document.addEventListener("input", (event) => {
    if (event.target.matches("textarea")) autosize(event.target);
  });
  $$("textarea").forEach(autosize);
}

/** The machine's own file dialog, as a promise: the picked file, or null
    if the reader closed it. Cancelling fires `cancel`, not `change` —
    without that arm the promise never settles and its caller waits
    forever. Two screens open it (a story to import, a premise to read),
    which is why it lives here rather than in either of them. */
export function pickFile(accept) {
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = accept;
    input.onchange = () => resolve(input.files[0] ?? null);
    input.oncancel = () => resolve(null);
    input.click();
  });
}
