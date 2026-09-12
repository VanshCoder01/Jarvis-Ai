"""
JarvisInstaller.py — a real installer with a GUI.

Downloads the latest Jarvis from GitHub, installs Python if it's missing,
installs every dependency, and puts a shortcut on the Desktop. The person
running it never touches a terminal.

Build it into a standalone .exe with:
    pyinstaller --onefile --noconsole --icon=jarvis.ico --name JarvisInstaller JarvisInstaller.py

Only stdlib is used here (tkinter, urllib, zipfile, subprocess) so the
installer itself has no dependencies to install before it can run.
"""
import io
import os
import shutil
import subprocess
import sys
import threading
import tkinter as tk
import urllib.request
import zipfile
from tkinter import ttk, messagebox

REPO = "VanshCoder01/Jarvis-Ai"
BRANCH = "main"
SOURCE_URL = f"https://codeload.github.com/{REPO}/zip/refs/heads/{BRANCH}"
INSTALL_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Jarvis")

BG = "#04070c"
PANEL = "#0b1622"
CYAN = "#6fe9f5"
TEXT = "#cfe9ef"
FAINT = "#5c7a80"


class Installer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Jarvis Installer")
        self.geometry("560x420")
        self.resizable(False, False)
        self.configure(bg=BG)
        self._build_ui()
        self.worker = None

    def _build_ui(self):
        tk.Label(self, text="J.A.R.V.I.S", bg=BG, fg=TEXT,
                 font=("Consolas", 20, "bold")).pack(pady=(28, 2))
        tk.Label(self, text="JUST A RATHER VERY INTELLIGENT SYSTEM", bg=BG, fg=FAINT,
                 font=("Consolas", 8)).pack()
        tk.Label(self, text=f"Installs to  {INSTALL_DIR}", bg=BG, fg=FAINT,
                 font=("Consolas", 8)).pack(pady=(14, 0))

        self.log_box = tk.Text(self, height=11, bg=PANEL, fg=TEXT, bd=0,
                               font=("Consolas", 9), wrap="word",
                               insertbackground=CYAN, padx=12, pady=10)
        self.log_box.pack(fill="both", expand=True, padx=26, pady=16)
        self.log_box.configure(state="disabled")

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("J.Horizontal.TProgressbar", troughcolor=PANEL,
                        background=CYAN, bordercolor=PANEL,
                        lightcolor=CYAN, darkcolor=CYAN)
        self.bar = ttk.Progressbar(self, style="J.Horizontal.TProgressbar",
                                   length=508, mode="determinate")
        self.bar.pack(padx=26)

        self.btn = tk.Button(self, text="INSTALL", command=self.start,
                             bg=CYAN, fg=BG, bd=0, font=("Consolas", 10, "bold"),
                             activebackground="#b6f6fb", cursor="hand2",
                             padx=20, pady=9)
        self.btn.pack(pady=18)

        self.log("Ready to install.")
        self.log(f"Source: github.com/{REPO}")

    # ---------- helpers ----------
    def log(self, msg):
        def _append():
            self.log_box.configure(state="normal")
            self.log_box.insert("end", msg + "\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        self.after(0, _append)

    def progress(self, value):
        self.after(0, lambda: self.bar.configure(value=value))

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        self.btn.configure(state="disabled", text="INSTALLING...")
        # Do the work off the UI thread so the window keeps repainting.
        self.worker = threading.Thread(target=self._run, daemon=True)
        self.worker.start()

    def _finish(self, ok, message):
        def _done():
            self.btn.configure(state="normal",
                               text="LAUNCH JARVIS" if ok else "RETRY")
            if ok:
                self.btn.configure(command=self.launch)
            messagebox.showinfo("Jarvis", message) if ok else \
                messagebox.showerror("Jarvis", message)
        self.after(0, _done)

    def launch(self):
        target = os.path.join(INSTALL_DIR, "main.py")
        try:
            pyw = self._find_python(windowless=True)
            subprocess.Popen([pyw, target], cwd=INSTALL_DIR)
            self.after(1200, self.destroy)
        except Exception as e:
            messagebox.showerror("Jarvis", f"Couldn't launch: {e}")

    def _find_python(self, windowless=False):
        """Finds a usable system Python. The installer's own bundled
        interpreter (when frozen by PyInstaller) can't run a separate app,
        so we need a real one on the machine."""
        names = ["pythonw", "python"] if windowless else ["python", "py"]
        for name in names:
            found = shutil.which(name)
            if found:
                return found
        raise RuntimeError("Python not found")

    # ---------- the actual install ----------
    def _run(self):
        try:
            # 1. Python
            self.log("")
            self.log("[1/4] Checking for Python...")
            try:
                py = self._find_python()
                ver = subprocess.run([py, "--version"], capture_output=True, text=True, timeout=20)
                self.log(f"      Found {ver.stdout.strip() or ver.stderr.strip()}")
            except Exception:
                self.log("      Not found. Installing Python 3.12 via winget...")
                self.log("      (this can take a few minutes)")
                r = subprocess.run(
                    ["winget", "install", "-e", "--id", "Python.Python.3.12",
                     "--accept-source-agreements", "--accept-package-agreements"],
                    capture_output=True, text=True,
                )
                if r.returncode != 0:
                    self._finish(False,
                                 "Couldn't install Python automatically.\n\n"
                                 "Install Python 3.12 from python.org (tick "
                                 "'Add python.exe to PATH'), then run this "
                                 "installer again.")
                    return
                self.log("      Python installed. You may need to re-run this "
                         "installer so Windows picks up the new PATH.")
                try:
                    py = self._find_python()
                except Exception:
                    self._finish(False, "Python installed. Please close this "
                                        "window and run the installer again.")
                    return
            self.progress(25)

            # 2. Download
            self.log("")
            self.log("[2/4] Downloading the latest version from GitHub...")
            req = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "JarvisInstaller"})
            with urllib.request.urlopen(req, timeout=90) as resp:
                blob = resp.read()
            self.log(f"      Downloaded {len(blob) // 1024} KB")
            self.progress(50)

            # 3. Extract
            self.log("")
            self.log("[3/4] Installing files...")
            os.makedirs(INSTALL_DIR, exist_ok=True)
            with zipfile.ZipFile(io.BytesIO(blob)) as zf:
                names = zf.namelist()
                root = names[0].split("/")[0] + "/"   # e.g. "Jarvis-Ai-main/"
                for name in names:
                    if name.endswith("/") or not name.startswith(root):
                        continue
                    rel = name[len(root):]
                    if not rel:
                        continue
                    dest = os.path.join(INSTALL_DIR, rel.replace("/", os.sep))
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with zf.open(name) as srcf, open(dest, "wb") as outf:
                        shutil.copyfileobj(srcf, outf)
            self.log(f"      Installed to {INSTALL_DIR}")
            self.progress(70)

            # 4. Dependencies
            self.log("")
            self.log("[4/4] Installing dependencies (this takes a minute)...")
            reqs = os.path.join(INSTALL_DIR, "requirements.txt")
            if os.path.exists(reqs):
                r = subprocess.run([py, "-m", "pip", "install", "-r", reqs],
                                   capture_output=True, text=True)
                if r.returncode != 0:
                    tail = (r.stderr or "").strip().splitlines()[-4:]
                    for line in tail:
                        self.log(f"      {line}")
                    self._finish(False, "Dependency install failed — see the log.")
                    return
                self.log("      Dependencies ready.")
            else:
                self.log("      No requirements.txt found; skipping.")
            self.progress(90)

            # Shortcut
            self.log("")
            self.log("Creating Desktop shortcut...")
            self._make_shortcut()
            self.progress(100)

            self.log("")
            self.log("Done. Jarvis is installed.")
            self._finish(True, "Jarvis installed successfully.\n\n"
                               "A shortcut is on your Desktop, or click "
                               "LAUNCH JARVIS below.")
        except Exception as e:
            self.log(f"ERROR: {e}")
            self._finish(False, f"Install failed:\n\n{e}")

    def _make_shortcut(self):
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        icon = os.path.join(INSTALL_DIR, "jarvis.ico")
        target = os.path.join(INSTALL_DIR, "main.py")
        try:
            pyw = self._find_python(windowless=True)
        except Exception:
            self.log("      Skipped (no pythonw found).")
            return
        ps = (
            "$s=(New-Object -COM WScript.Shell).CreateShortcut("
            f"'{os.path.join(desktop, 'Jarvis.lnk')}');"
            f"$s.TargetPath='{pyw}';"
            f"$s.Arguments='\"{target}\"';"
            f"$s.WorkingDirectory='{INSTALL_DIR}';"
            + (f"$s.IconLocation='{icon}';" if os.path.exists(icon) else "")
            + "$s.Description='Jarvis voice assistant';$s.Save()"
        )
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, text=True)
        self.log("      Shortcut created." if r.returncode == 0
                 else "      Couldn't create the shortcut (not fatal).")


if __name__ == "__main__":
    if sys.platform != "win32":
        print("This installer is for Windows.")
    Installer().mainloop()
