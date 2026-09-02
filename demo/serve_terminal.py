#!/usr/bin/env python3
"""Serve the built terminal demo locally, with the two cross-origin
isolation headers SharedArrayBuffer requires — the stdlib server plus
the two headers a host must add under the deployed folder:

    demo/serve_terminal.py [dir] [port]     (default dist/demo-terminal 8917)
"""

import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt: str, *args: object) -> None:
        pass


def main() -> None:
    directory = sys.argv[1] if len(sys.argv) > 1 else "dist/demo-terminal"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8917
    server = ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, directory=directory))
    print(f"serving {directory} at http://127.0.0.1:{port}/")
    server.serve_forever()


if __name__ == "__main__":
    main()
