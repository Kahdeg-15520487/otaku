/* The page's half of the terminal demo: an xterm.js terminal wired to
   the worker that runs the real application. Keystrokes go into a
   SharedArrayBuffer ring (the worker blocks on it with Atomics.wait —
   the page never blocks); output comes back as messages; the terminal's
   size sits in a second shared array the worker reads per render.

   xterm.js answers the application's own terminal queries — OSC 11 with
   the theme background below, DSR 6 with the cursor position — so the
   adaptive theme and the screen ledger run the same code paths a native
   terminal exercises. */

const RING_BYTES = 65536;

// A light terminal: the OSC 11 answer below reports this background,
// so the application's adaptive theme settles LIGHT on its own.
const theme = {
  background: "#fafafa",
  foreground: "#1f2328",
  cursor: "#1f2328",
  selectionBackground: "#d7dbe8",
};

const term = new Terminal({
  // The application prints "\n" and lets the tty's ONLCR bring the
  // carriage back; xterm.js has no line discipline, so it does the
  // translation itself.
  convertEol: true,
  fontSize: 15,
  fontFamily: '"SF Mono", "Cascadia Mono", "JetBrains Mono", Menlo, Consolas, monospace',
  // Exactly 1: the banner mascot is half-block art, and any leading
  // padding is filled with the cell background — which stretches every
  // lower pixel and shears the picture apart.
  lineHeight: 1,
  cursorBlink: true,
  scrollback: 8000,
  theme,
});
const fit = new FitAddon.FitAddon();
term.loadAddon(fit);
term.open(document.getElementById("terminal"));
// The WebGL renderer draws block elements as exact rectangles
// (customGlyphs) instead of font glyphs, which is what keeps the
// mascot's pixels square and seamless; without WebGL the DOM renderer
// still works, just with the font's own half-blocks.
try {
  term.loadAddon(new WebglAddon.WebglAddon());
} catch (error) {
  console.warn("webgl renderer unavailable, using the DOM renderer", error);
}
fit.fit();
term.focus();
window.term = term; // the smoke test reads the screen through this

const ring = new SharedArrayBuffer(8 + RING_BYTES);
const meta = new Int32Array(ring, 0, 2); // [head, tail]
const data = new Uint8Array(ring, 8);
const dimsBuffer = new SharedArrayBuffer(8);
const dims = new Int32Array(dimsBuffer);

const measure = () => {
  Atomics.store(dims, 0, term.cols);
  Atomics.store(dims, 1, term.rows);
};
measure();
addEventListener("resize", () => {
  fit.fit();
  measure();
});

const encoder = new TextEncoder();
let overflow = [];

function enqueue(bytes) {
  for (const byte of bytes) overflow.push(byte);
  drain();
}

function drain() {
  const size = data.length;
  let head = Atomics.load(meta, 0);
  const tail = Atomics.load(meta, 1);
  let free = (tail - head - 1 + size) % size;
  while (overflow.length && free > 0) {
    data[head] = overflow.shift();
    head = (head + 1) % size;
    free--;
  }
  Atomics.store(meta, 0, head);
  Atomics.notify(meta, 0);
  if (overflow.length) setTimeout(drain, 15); // a paste larger than the ring
}

term.onData((text) => enqueue(encoder.encode(text)));

const status = document.getElementById("status");
const worker = new Worker("worker.js");
worker.onmessage = (event) => {
  const message = event.data;
  if (message.type === "out") {
    term.write(message.data);
  } else if (message.type === "status") {
    status.textContent = message.text;
    status.hidden = !message.text;
  } else if (message.type === "exit") {
    status.textContent = "the session is over — reload to start again";
    status.hidden = false;
  } else if (message.type === "crash") {
    status.textContent = "something broke — the console has the details";
    status.hidden = false;
    term.write(`\r\n\x1b[31m${message.text}\x1b[0m\r\n`);
  }
};

worker.postMessage({
  type: "start",
  ring,
  dims: dimsBuffer,
  wheels: [
    "./wheels/prompt_toolkit-3.0.53-py3-none-any.whl",
    "./wheels/wcwidth-0.8.3-py3-none-any.whl",
    "./wheels/otaku-0.4.0-py3-none-any.whl",
  ],
});
