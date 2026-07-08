"""
pc_control.py — Jarvis's hands. Every function here actually touches the PC.

Targets Windows (this is built for your ROG Strix). A few functions
(lock/sleep/shutdown, volume media-keys) are Windows-specific by design.
"""
import os
import subprocess
from datetime import datetime

import pyautogui

import config

pyautogui.FAILSAFE = True  # slam the mouse into a screen corner to abort a runaway action
SCREEN_W, SCREEN_H = pyautogui.size()


# ---------- Apps ----------
def open_app(name: str) -> str:
    key = (name or "").strip().lower()
    target = config.APP_PATHS.get(key, name)
    try:
        os.system(f'start "" "{target}"')
        return f"Opened {name}."
    except Exception as e:
        return f"Couldn't open {name} ({e})."


def close_app(name: str) -> str:
    key = (name or "").strip().lower()
    target = config.APP_PATHS.get(key, name)
    exe = os.path.basename(target)
    if not exe.lower().endswith(".exe"):
        exe += ".exe"
    try:
        subprocess.run(["taskkill", "/IM", exe, "/F"], capture_output=True)
        return f"Closed {name}."
    except Exception as e:
        return f"Couldn't close {name} ({e})."


# ---------- Cursor & clicks ----------
ZONES = {
    "center": (0.5, 0.5),
    "top left": (0.05, 0.05),
    "top right": (0.95, 0.05),
    "bottom left": (0.05, 0.95),
    "bottom right": (0.95, 0.95),
    "top": (0.5, 0.05),
    "bottom": (0.5, 0.95),
}


def move_cursor(zone: str = None, dx: int = 0, dy: int = 0) -> str:
    if zone and zone.lower() in ZONES:
        fx, fy = ZONES[zone.lower()]
        pyautogui.moveTo(int(SCREEN_W * fx), int(SCREEN_H * fy), duration=0.3)
        return f"Cursor moved to {zone}."
    x, y = pyautogui.position()
    pyautogui.moveTo(x + dx, y + dy, duration=0.2)
    return "Cursor moved."


def click(button: str = "left") -> str:
    pyautogui.click(button=button if button in ("left", "right", "middle") else "left")
    return f"{button.capitalize()} click."


def double_click() -> str:
    pyautogui.doubleClick()
    return "Double-clicked."


def scroll(amount: int = 10) -> str:
    pyautogui.scroll(int(amount) * 30)
    return "Scrolled."


def type_text(text: str) -> str:
    pyautogui.write(text or "", interval=0.02)
    return f"Typed: {text}"


def press_key(key: str) -> str:
    try:
        pyautogui.press(key)
        return f"Pressed {key}."
    except Exception as e:
        return f"Couldn't press {key} ({e})."


# ---------- Volume ----------
def set_volume(direction: str = None, steps: int = 5) -> str:
    key = {"up": "volumeup", "down": "volumedown"}.get((direction or "").lower())
    if key:
        for _ in range(steps):
            pyautogui.press(key)
        return f"Volume {direction}."
    return "Didn't catch a volume direction."


def mute() -> str:
    pyautogui.press("volumemute")
    return "Muted."


# ---------- Brightness ----------
def set_brightness(level=None, direction: str = None, step: int = 15) -> str:
    try:
        import screen_brightness_control as sbc
        if level:
            target = max(0, min(100, int(level)))
        elif direction:
            current = sbc.get_brightness()
            current = current[0] if isinstance(current, list) else current
            delta = step if direction == "up" else -step if direction == "down" else 0
            target = max(0, min(100, current + delta))
        else:
            target = 50
        sbc.set_brightness(target)
        return f"Brightness set to {target}%."
    except Exception as e:
        return f"Couldn't change brightness ({e}). Some laptop panels block external control."


# ---------- Power ----------
def lock_pc() -> str:
    import ctypes
    ctypes.windll.user32.LockWorkStation()
    return "Locked."


def sleep_pc() -> str:
    subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
    return "Going to sleep."


def shutdown_pc(seconds: int = 10) -> str:
    subprocess.run(["shutdown", "/s", "/t", str(seconds)])
    return f"Shutting down in {seconds} seconds. Say 'cancel shutdown' to stop it."


def restart_pc(seconds: int = 10) -> str:
    subprocess.run(["shutdown", "/r", "/t", str(seconds)])
    return f"Restarting in {seconds} seconds. Say 'cancel shutdown' to stop it."


def cancel_shutdown() -> str:
    subprocess.run(["shutdown", "/a"])
    return "Shutdown cancelled."


# ---------- Misc ----------
def screenshot() -> str:
    folder = os.path.join(os.path.expanduser("~"), "Pictures", "Jarvis")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"shot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
    pyautogui.screenshot(path)
    return f"Screenshot saved to {path}."


def get_time() -> str:
    return datetime.now().strftime("It's %I:%M %p.")


# ---------- System stats ----------
_cpu_primed = False


def get_system_stats() -> dict:
    """CPU%, RAM%, temp (best-effort), and OS info for the UI's stats strip.
    Never raises — anything unavailable just comes back as None so the UI
    shows 'N/A' instead of breaking."""
    global _cpu_primed
    import platform as _platform

    stats = {
        "cpu_percent": None,
        "ram_percent": None,
        "ram_used_gb": None,
        "ram_total_gb": None,
        "temp_c": None,
        "os": f"{_platform.system()} {_platform.release()}",
    }

    try:
        import psutil
        if not _cpu_primed:
            # First call to cpu_percent always returns a meaningless 0.0 —
            # this "primes" it so every call after this one is real.
            psutil.cpu_percent(interval=None)
            _cpu_primed = True
            stats["cpu_percent"] = round(psutil.cpu_percent(interval=0.2))
        else:
            stats["cpu_percent"] = round(psutil.cpu_percent(interval=None))
        mem = psutil.virtual_memory()
        stats["ram_percent"] = round(mem.percent)
        stats["ram_used_gb"] = round(mem.used / (1024 ** 3), 1)
        stats["ram_total_gb"] = round(mem.total / (1024 ** 3), 1)
    except Exception:
        pass

    try:
        stats["temp_c"] = _read_temp_c()
    except Exception:
        pass

    return stats


def _read_temp_c():
    """Best-effort CPU temp via WMI. A lot of laptop boards (including plenty
    of gaming laptops) just don't expose this through Windows' standard
    thermal-zone API — None here is normal/expected, not a bug. If it's
    always None on your machine, LibreHardwareMonitor is the reliable fix."""
    import wmi
    w = wmi.WMI(namespace="root\\wmi")
    zones = w.MSAcpi_ThermalZoneTemperature()
    if not zones:
        return None
    tenths_kelvin = zones[0].CurrentTemperature
    return round((tenths_kelvin / 10.0) - 273.15, 1)
