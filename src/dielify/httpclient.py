"""One way to make long-lived HTTP sessions that survive dropped idle connections.

Sessions keep connections open between requests. Servers (GitHub, YouTube) close idle
ones at their end, and the next request on such a connection fails with "Connection
aborted / ConnectionResetError 10054". Retrying GETs on a fresh connection fixes that.
"""

from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def retrying_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=3, connect=3, read=3, backoff_factor=0.5, allowed_methods=frozenset({"GET"}),
                  status_forcelist=(502, 503, 504), raise_on_status=False)
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s
