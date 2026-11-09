"""The PC announces itself on the home network (mDNS / DNS-SD, like printers do), so the TV
app finds it without anyone typing an address (0.9.10).

Only home-network addresses are announced, never loopback or Tailscale, and only on those
network cards. The announcement holds the address, the port and Dielify's version: nothing
else, and finding the PC doesn't let anything in (signing in still needs a phone's OK).
"""
from __future__ import annotations

import ipaddress
import logging
import platform
import socket
import threading

from . import __version__

log = logging.getLogger(__name__)
SERVICE = "_dielify._tcp.local."


def home_addresses(addrs) -> list[str]:
    """The home-network (private, not Tailscale, not loopback) IPv4 addresses among addrs."""
    out = []
    for a in addrs:
        try:
            ip = ipaddress.ip_address(a)
        except ValueError:
            continue
        if ip.version == 4 and ip.is_private and not ip.is_loopback and ip not in ipaddress.ip_network("100.64.0.0/10"):
            out.append(a)
    return sorted(set(out), key=ipaddress.ip_address)


class Announcer:
    def __init__(self, port: int):
        self.port = port
        self._addrs: list[str] = []
        self._zc = None
        self._info = None
        self._lock = threading.Lock()

    def update(self, bound) -> None:
        """(Re)announce on the home addresses among `bound`; quiet if there are none."""
        addrs = home_addresses(bound)
        with self._lock:
            if addrs == self._addrs:
                return
            self._close()
            self._addrs = addrs
            if not addrs:
                return
            try:
                from zeroconf import ServiceInfo, Zeroconf
                name = platform.node() or "PC"
                self._info = ServiceInfo(
                    SERVICE, f"Dielify on {name}.{SERVICE}",
                    addresses=[socket.inet_aton(a) for a in addrs], port=self.port,
                    properties={"version": __version__, "name": name},
                    server=f"dielify-{name.lower()}.local.")
                self._zc = Zeroconf(interfaces=addrs)
                self._zc.register_service(self._info, allow_name_change=True)
                log.info("Announced on the home network: %s port %d", ", ".join(addrs), self.port)
            except Exception as e:  # noqa: BLE001 - the TV can still be given the address by hand
                log.warning("Couldn't announce Dielify on the home network (%s)", e)
                self._close()

    def _close(self) -> None:
        if self._zc is not None:
            try:
                if self._info is not None:
                    self._zc.unregister_service(self._info)
                self._zc.close()
            except Exception:  # noqa: BLE001
                pass
        self._zc = self._info = None

    def close(self) -> None:
        with self._lock:
            self._close()
            self._addrs = []
