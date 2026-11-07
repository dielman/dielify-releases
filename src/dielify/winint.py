"""Windows integration for the desktop app: one copy at a time, "show the window"
signal, start with Windows, message boxes."""

from __future__ import annotations

import ctypes
import sys
import winreg
from ctypes import wintypes
from pathlib import Path
from typing import Callable

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CreateEventW.restype = wintypes.HANDLE
_kernel32.OpenEventW.restype = wintypes.HANDLE
_user32 = ctypes.WinDLL("user32", use_last_error=True)

MUTEX_NAME = "Local\\dielify-desktop"          # Local\ = this Windows session only
SHOW_EVENT_NAME = "Local\\dielify-desktop-show"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "Dielify"
ERROR_ALREADY_EXISTS = 183
EVENT_MODIFY_STATE = 0x0002
INFINITE = 0xFFFFFFFF

_mutex = None  # kept for the life of the process


def claim_single_instance() -> bool:
    """True if this is the only running copy of the desktop app."""
    global _mutex
    _mutex = _kernel32.CreateMutexW(None, False, MUTEX_NAME)
    return ctypes.get_last_error() != ERROR_ALREADY_EXISTS


def signal_show() -> bool:
    """Ask the running copy to bring its window forward."""
    handle = _kernel32.OpenEventW(EVENT_MODIFY_STATE, False, SHOW_EVENT_NAME)
    if not handle:
        return False
    _kernel32.SetEvent(handle)
    _kernel32.CloseHandle(handle)
    return True


def wait_for_show(on_show: Callable[[], None]) -> None:
    """Run forever (in a thread): call `on_show` each time another copy is started."""
    event = _kernel32.CreateEventW(None, False, False, SHOW_EVENT_NAME)
    while True:
        _kernel32.WaitForSingleObject(event, INFINITE)
        on_show()


def message_box(text: str, title: str = "Dielify", error: bool = True) -> None:
    MB_ICONERROR, MB_ICONINFORMATION = 0x10, 0x40
    _user32.MessageBoxW(None, text, title, MB_ICONERROR if error else MB_ICONINFORMATION)


# --- start with Windows -------------------------------------------------------------

def launch_command() -> str:
    """How Windows should start the app at sign-in (straight to the tray)."""
    if getattr(sys, "frozen", False):  # the installed app
        return f'"{sys.executable}" --tray'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return f'"{pythonw}" -m dielify.desktop --tray'


def start_with_windows() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_VALUE)
            return True
    except OSError:
        return False


def set_start_with_windows(enabled: bool) -> None:
    """Per-user 'run at sign-in' entry (HKCU\\...\\Run). No admin rights involved."""
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, RUN_VALUE, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(k, RUN_VALUE)
            except FileNotFoundError:
                pass
