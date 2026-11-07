"""Developer helper: serve the desktop screens on this PC only, for a normal browser.

    .venv\\Scripts\\python tools\\dev_ui.py [port]

Prints a link with a one-off key. Uses the real settings and library. The
folder picker and YouTube sign-in only work in the real app window.
"""

import sys

from dielify import auth, server
from dielify import settings as settings_mod

port = int(sys.argv[1]) if len(sys.argv) > 1 else 4748
s = settings_mod.load()
s.server_port = port
token = auth.enable_desktop_token()
print(f"Open: http://127.0.0.1:{port}/ui/#t={token}", flush=True)
server.run(s, ["127.0.0.1"])
