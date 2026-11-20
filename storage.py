"""
storage.py — safe reading and writing of Jarvis's JSON files
(jarvis_memory.json, jarvis_history.json, jarvis_sessions.json).

Why this exists: the server answers requests on several threads at once,
and the old code saved with a plain open(path, "w"). That truncates the
file first and fills it afterwards, so a request reading at the wrong
moment saw an empty or half-written file, fell back to defaults, and the
next save wrote those defaults back -- wiping every stored API key and
remembered fact. A crash mid-save did the same.

So:
  * writes go to a temp file in the same folder and are swapped in with
    os.replace(), which is atomic -- a reader sees the old file or the new
    one, never half of either;
  * reads and writes share one lock, which also sidesteps Windows refusing
    to replace a file another thread has open;
  * a file that really is corrupt is copied aside (".corrupt-<time>")
    before anything can overwrite it, so nothing is silently lost.
"""
import json
import os
import tempfile
import threading
import time

_lock = threading.RLock()


def lock():
    """For read-modify-write sequences that must not interleave with
    another thread's: `with storage.lock(): data = load(); ...; save(data)`."""
    return _lock


def _retry(fn, attempts=5, delay=0.05):
    # Antivirus and indexers briefly hold files open on Windows, which
    # makes open()/os.replace() fail with PermissionError for a moment.
    for i in range(attempts):
        try:
            return fn()
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(delay * (i + 1))


def _quarantine(path):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = f"{path}.corrupt-{stamp}"
    try:
        os.replace(path, backup)
        print(f"(storage) {os.path.basename(path)} was unreadable; kept a copy at {backup}")
    except OSError:
        pass


def read_json(path, default_factory):
    """Returns the parsed file, or default_factory() if it doesn't exist
    or is corrupt (a corrupt file is moved aside first, never discarded)."""
    with _lock:
        if not os.path.exists(path):
            return default_factory()

        def _read():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)

        try:
            return _retry(_read)
        except ValueError:
            _quarantine(path)
        except OSError:
            pass
        return default_factory()


def write_json(path, data, indent=2):
    """Atomically replaces path with data serialised as JSON."""
    with _lock:
        folder = os.path.dirname(os.path.abspath(path))
        os.makedirs(folder, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=folder)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=indent)
                f.flush()
                os.fsync(f.fileno())
            _retry(lambda: os.replace(tmp, path))
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
