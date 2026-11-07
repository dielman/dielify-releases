"""Developer helper: serve the desktop screens on this PC only, for a normal browser.

    .venv\\Scripts\\python tools\\dev_ui.py [port]

Prints a link with a one-off key. Uses the real settings and library, but does NOT
download anything: the installed app may be working through the same queue.
The folder picker and YouTube sign-in only work in the real app window.
"""

import sys

import uvicorn

from dielify import auth, server
from dielify import settings as settings_mod
from dielify.downloads import DownloadQueue


class ViewOnlyQueue(DownloadQueue):
    def start(self) -> None:  # no worker: never competes with the installed app
        pass


port = int(sys.argv[1]) if len(sys.argv) > 1 else 4748
s = settings_mod.load()
s.server_port = port
token = auth.enable_desktop_token()
print(f"Open: http://127.0.0.1:{port}/ui/#t={token}", flush=True)
uvicorn.run(server.create_app(ViewOnlyQueue()), host="127.0.0.1", port=port, log_level="warning")
