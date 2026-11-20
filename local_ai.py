"""
local_ai.py — "run Jarvis on a local model" in one click.

1. Looks at this PC (RAM, and the graphics card's own memory if it has one).
2. Recommends the biggest model that will run comfortably on it.
3. Installs Ollama if it isn't there (winget, or the official installer as a
   fallback), makes sure it's running, and pulls the model -- reporting
   progress so the UI can draw a bar.

When it finishes, the UI adds the key "ollama:<model>" like any other key,
and llm.py's existing Ollama support takes it from there.

Nothing here goes through a shell: every command is an argument list, and
the model name has to be one from CATALOGUE below.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

import psutil

import llm

# Qwen 2.5 is the family Jarvis already prefers for Ollama: it follows the
# JSON action schema reliably at every size. Sizes are the 4-bit downloads
# Ollama serves by default; "need" is memory to run it with some headroom.
CATALOGUE = [
    {"id": "qwen2.5:32b",  "label": "Qwen 2.5 32B",  "download_gb": 20.0, "need_gb": 22, "note": "Best answers. Needs a big graphics card."},
    {"id": "qwen2.5:14b",  "label": "Qwen 2.5 14B",  "download_gb": 9.0,  "need_gb": 11, "note": "Very capable. Great on a 12 GB+ card."},
    {"id": "qwen2.5:7b",   "label": "Qwen 2.5 7B",   "download_gb": 4.7,  "need_gb": 6,  "note": "The sweet spot for most gaming PCs."},
    {"id": "qwen2.5:3b",   "label": "Qwen 2.5 3B",   "download_gb": 1.9,  "need_gb": 3,  "note": "Quick on laptops; fine for commands."},
    {"id": "qwen2.5:1.5b", "label": "Qwen 2.5 1.5B", "download_gb": 1.0,  "need_gb": 2,  "note": "For older or low-memory PCs."},
]
_IDS = {m["id"] for m in CATALOGUE}
# Without a usable graphics card the CPU does the work; beyond ~7B that gets
# too slow to feel like an assistant, however much RAM there is.
_CPU_MAX_NEED_GB = 6

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_OLLAMA_INSTALLER_URL = "https://ollama.com/download/OllamaSetup.exe"


# ---------- hardware ----------
def _nvidia_gpus():
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    try:
        out = subprocess.run([exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=8, creationflags=_NO_WINDOW).stdout
    except Exception:
        return []
    gpus = []
    for line in out.strip().splitlines():
        name, _, mem = line.rpartition(",")
        try:
            gpus.append({"name": name.strip(), "vram_gb": round(float(mem) / 1024, 1)})
        except ValueError:
            pass
    return gpus


def _registry_gpus():
    """Every display adapter Windows knows about, with its real dedicated
    memory (WMI's AdapterRAM tops out at 4 GB, so read the registry)."""
    if sys.platform != "win32":
        return []
    import winreg
    gpus = []
    cls = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, cls)
    except OSError:
        return []
    for i in range(32):
        try:
            sub = winreg.EnumKey(root, i)
        except OSError:
            break
        if not sub.isdigit():
            continue
        try:
            with winreg.OpenKey(root, sub) as k:
                name = winreg.QueryValueEx(k, "DriverDesc")[0]
                try:
                    mem = winreg.QueryValueEx(k, "HardwareInformation.qwMemorySize")[0]
                except OSError:
                    mem = winreg.QueryValueEx(k, "HardwareInformation.MemorySize")[0]
                if isinstance(mem, bytes):
                    mem = int.from_bytes(mem, "little")
                gpus.append({"name": str(name), "vram_gb": round(int(mem) / 1024 ** 3, 1)})
        except (OSError, ValueError, TypeError):
            continue
    return gpus


def detect_hardware():
    ram_gb = round(psutil.virtual_memory().total / 1024 ** 3, 1)
    gpus = _nvidia_gpus() or _registry_gpus()
    # Integrated graphics borrow system RAM and Ollama won't use them, so only
    # a card with real memory of its own counts as a GPU here.
    usable = [g for g in gpus if g["vram_gb"] >= 3.5 and "intel" not in g["name"].lower()
              and "microsoft basic" not in g["name"].lower()]
    best = max(usable, key=lambda g: g["vram_gb"]) if usable else None
    return {"ram_gb": ram_gb, "gpu": best["name"] if best else "",
            "vram_gb": best["vram_gb"] if best else 0.0,
            "free_disk_gb": round(shutil.disk_usage(os.path.expanduser("~")).free / 1024 ** 3, 1)}


def recommend(hw=None):
    hw = hw or detect_hardware()
    if hw["vram_gb"]:
        # the model goes in the card's memory; spill-over into RAM still runs, just slower
        budget, why = hw["vram_gb"], f"your {hw['gpu']} ({hw['vram_gb']:g} GB)"
    else:
        budget = min(hw["ram_gb"] * 0.5, _CPU_MAX_NEED_GB)
        why = f"{hw['ram_gb']:g} GB of RAM and no dedicated graphics card"
    pick = next((m for m in CATALOGUE if m["need_gb"] <= budget), CATALOGUE[-1])
    options = []
    for m in CATALOGUE:
        fit = "good" if m["need_gb"] <= budget else ("slow" if m["need_gb"] <= budget + hw["ram_gb"] * 0.5 else "too big")
        if m["download_gb"] + 1 > hw["free_disk_gb"]:
            fit = "no disk space"
        options.append({**m, "fit": fit})
    ollama = llm.ollama_status()
    return {"hardware": hw, "recommended": pick["id"],
            "reason": f"Picked for {why}.", "options": options,
            "ollama_installed": bool(ollama["running"] or _find_ollama_exe()),
            "installed_models": ollama["models"]}


# ---------- install + pull ----------
_lock = threading.Lock()
_status = {"state": "idle", "model": "", "message": "", "progress": 0.0, "error": ""}


def status():
    with _lock:
        return dict(_status)


def _set(**kw):
    with _lock:
        _status.update(kw)


def _find_ollama_exe():
    found = shutil.which("ollama")
    if found:
        return found
    guess = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe")
    return guess if os.path.isfile(guess) else None


def _install_ollama():
    winget = shutil.which("winget")
    if winget:
        _set(message="Installing Ollama with winget…")
        r = subprocess.run([winget, "install", "-e", "--id", "Ollama.Ollama", "--silent",
                            "--accept-package-agreements", "--accept-source-agreements",
                            "--disable-interactivity"],
                           capture_output=True, text=True, timeout=1200, creationflags=_NO_WINDOW)
        if _find_ollama_exe():
            return
        if r.returncode not in (0,):
            print(f"(local_ai) winget failed ({r.returncode}): {(r.stdout or '')[-400:]}")
    _set(message="Downloading the Ollama installer…")
    folder = tempfile.mkdtemp(prefix="jarvis_ollama_")
    setup = os.path.join(folder, "OllamaSetup.exe")
    urllib.request.urlretrieve(_OLLAMA_INSTALLER_URL, setup)
    _set(message="Installing Ollama…")
    subprocess.run([setup, "/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES"], timeout=1200)
    if not _find_ollama_exe():
        raise RuntimeError("Ollama's installer finished but ollama.exe isn't where it should be. "
                           "Install it from ollama.com, then try again.")


def _ensure_running(timeout=60):
    if llm.ollama_status()["running"]:
        return
    exe = _find_ollama_exe()
    if not exe:
        raise RuntimeError("Ollama isn't installed.")
    _set(message="Starting Ollama…")
    flags = _NO_WINDOW | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen([exe, "serve"], creationflags=flags,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if llm.ollama_status()["running"]:
            return
        time.sleep(1)
    raise RuntimeError("Ollama is installed but didn't start. Open the Ollama app once, then try again.")


def _pull(model):
    base = llm.ollama_default_host()
    req = urllib.request.Request(base + "/api/pull", method="POST",
                                 data=json.dumps({"model": model, "stream": True}).encode(),
                                 headers={"Content-Type": "application/json"})
    layers = {}
    with urllib.request.urlopen(req, timeout=60) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            ev = json.loads(line)
            if ev.get("error"):
                raise RuntimeError(f"Ollama couldn't download {model}: {ev['error']}")
            if ev.get("digest") and ev.get("total"):
                layers[ev["digest"]] = (ev.get("completed", 0), ev["total"])
            done = sum(c for c, _ in layers.values())
            total = sum(t for _, t in layers.values()) or 1
            msg = ev.get("status", "")
            if layers:
                msg = f"Downloading {model}: {done / 1024 ** 3:.1f} of {total / 1024 ** 3:.1f} GB"
            _set(message=msg, progress=min(done / total, 1.0))
            if ev.get("status") == "success":
                return
    raise RuntimeError("The download ended early. Check your connection and try again.")


def _worker(model):
    try:
        if not _find_ollama_exe() and not llm.ollama_status()["running"]:
            _set(state="installing", message="Installing Ollama…")
            _install_ollama()
        _set(state="starting")
        _ensure_running()
        if any(llm._name_matches(model, n) for n in llm.ollama_installed_models()):
            _set(state="done", progress=1.0, message=f"{model} is ready.")
            return
        _set(state="pulling", message=f"Downloading {model}…", progress=0.0)
        _pull(model)
        _set(state="done", progress=1.0, message=f"{model} is installed and ready.")
    except Exception as e:
        _set(state="error", error=str(e) or e.__class__.__name__, message="")


def start(model):
    """Kicks off install + download on a background thread."""
    if model not in _IDS:
        raise ValueError("Pick one of the listed models.")
    with _lock:
        if _status["state"] in ("installing", "starting", "pulling"):
            raise ValueError("Already setting up a model — hang on.")
        _status.update(state="starting", model=model, message="Getting ready…", progress=0.0, error="")
    threading.Thread(target=_worker, args=(model,), daemon=True).start()
    return status()
