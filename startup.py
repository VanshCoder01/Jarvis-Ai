"""
startup.py — "launch Jarvis when I sign in to Windows".

Uses the per-user Run key (HKCU\\...\\CurrentVersion\\Run), the same place
the Settings app's Startup Apps list reads from. No admin rights needed, and
it shows up there so it can be switched off from Windows as well as from
Jarvis's own settings panel.
"""
import os
import sys

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "Jarvis"


def launch_command() -> str:
    """What Windows should run at sign-in: the packaged .exe if this is one,
    otherwise pythonw (no console window) on main.py."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    here = os.path.dirname(os.path.abspath(__file__))
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    interpreter = pythonw if os.path.isfile(pythonw) else sys.executable
    return f'"{interpreter}" "{os.path.join(here, "main.py")}"'


def is_enabled() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, _VALUE_NAME)
            return bool(value)
    except Exception:
        return False


def set_enabled(enabled: bool) -> bool:
    """Returns the resulting state. Raises OSError if the registry refuses."""
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(key, _VALUE_NAME)
            except FileNotFoundError:
                pass
    return is_enabled()
