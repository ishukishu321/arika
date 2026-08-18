"""
Arika Maintenance Tool — Reset / Uninstall
-------------------------------------------
GUI (tkinter) utility to:
  1. RESET  -> wipe user/guest data, keys, uploads, audio (app stays installed)
  2. UNINSTALL -> delete the whole project folder (optionally keep Python/Node
     packages installed on the system)

Safe by design:
  - Nothing is deleted until the user explicitly ticks it AND confirms twice.
  - Reset recreates empty folders (with .gitkeep) so the app keeps working
    after a reset without needing a reinstall.
  - Uninstall can't delete itself while running, so it hands off to a small
    generated .bat that waits for this process to exit, then removes the
    project folder and deletes itself.

Run this with: python reset_uninstall.py  (or double-click if .py is
associated with Python on this PC).
"""

import os
import sys
import shutil
import subprocess
import tempfile
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import messagebox, ttk

try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

# --------------------------------------------------------------------------
# Paths (mirrors installer.py's layout)
# --------------------------------------------------------------------------
PROJECT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = PROJECT_DIR / "backend"
MEMORY_ROOT = BACKEND_DIR / "memory"
FRONTEND_STATIC = PROJECT_DIR / "frontend" / "static"
MINECRAFT_BOT_DIR = PROJECT_DIR / "minecraft_bot"
REQUIREMENTS_FILE = PROJECT_DIR / "requirements.txt"

USER_HOME = Path(os.path.expanduser("~"))
if (USER_HOME / "OneDrive" / "Desktop").exists():
    DESKTOP_DIR = USER_HOME / "OneDrive" / "Desktop"
else:
    DESKTOP_DIR = USER_HOME / "Desktop"
SHORTCUT_PATH = DESKTOP_DIR / "Arika AI.lnk"

# --------------------------------------------------------------------------
# Theme (same palette as installer.py, for a consistent feel)
# --------------------------------------------------------------------------
BG_MAIN = "#11111b"
BG_SEC = "#1e1e2e"
FG_NORM = "#bac2de"
FG_HL = "#cdd6f4"
FG_ACCENT = "#89b4fa"
FG_SUCCESS = "#a6e3a1"
FG_ERROR = "#f38ba8"
FG_WARN = "#f9e2af"
BTN_BG = "#313244"
BTN_HOVER = "#45475a"
FONT_MAIN = "Segoe UI"

# --------------------------------------------------------------------------
# Reset targets: (label, path, is_dir, default_checked)
# Directories are emptied (and recreated with a .gitkeep) rather than
# removed outright, so the app can keep running right after a reset.
# --------------------------------------------------------------------------
def reset_targets():
    return [
        {
            "label": "User accounts & memory (chats, profile, tasks, plans)",
            "path": MEMORY_ROOT / "users",
            "is_dir": True,
            "default": True,
        },
        {
            "label": "Guest data (guest chats, guest settings)",
            "path": MEMORY_ROOT / "guest",
            "is_dir": True,
            "default": True,
        },
        {
            "label": "Login accounts & admin record (users.json, admin.txt)",
            "path": [MEMORY_ROOT / "users.json", MEMORY_ROOT / "admin.txt"],
            "is_dir": False,
            "default": True,
        },
        {
            "label": "Recent-chats index (static_short_term.json)",
            "path": MEMORY_ROOT / "static_short_term.json",
            "is_dir": False,
            "default": True,
        },
        {
            "label": "Gemini API key (backend/memory/api_key.txt)",
            "path": MEMORY_ROOT / "api_key.txt",
            "is_dir": False,
            "default": True,
        },
        {
            "label": "Flask secret key (backend/memory/flask_secret.key)",
            "path": MEMORY_ROOT / "flask_secret.key",
            "is_dir": False,
            "default": True,
        },
        {
            "label": "Uploaded files (webcam photos, screenshots, chat uploads)",
            "path": FRONTEND_STATIC / "uploads",
            "is_dir": True,
            "default": True,
        },
        {
            "label": "Generated audio (TTS output)",
            "path": FRONTEND_STATIC / "audio",
            "is_dir": True,
            "default": True,
        },
        {
            "label": "Embedding model cache (large — re-downloads on next run)",
            "path": MEMORY_ROOT / ".embedding_model_cache",
            "is_dir": True,
            "default": False,
        },
    ]


class MaintenanceApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Arika Maintenance")
        self.root.geometry("650x600")
        self.root.resizable(False, False)
        self.root.configure(bg=BG_MAIN)

        self.frame = tk.Frame(root, padx=25, pady=20, bg=BG_MAIN)
        self.frame.pack(fill="both", expand=True)

        self.header = tk.Label(self.frame, text="Arika Maintenance", font=(FONT_MAIN, 20, "bold"), fg=FG_ACCENT, bg=BG_MAIN)
        self.header.pack(anchor="w")

        self.subtitle = tk.Label(self.frame, text="Reset your data, or remove Arika from this PC.", font=(FONT_MAIN, 10), fg=FG_NORM, bg=BG_MAIN)
        self.subtitle.pack(anchor="w", pady=(0, 16))

        self.body = tk.Frame(self.frame, bg=BG_MAIN)
        self.body.pack(fill="both", expand=True)

        self.show_home()

    # ---------------------------------------------------------- utilities
    def clear_body(self):
        for w in self.body.winfo_children():
            w.destroy()

    def btn_style(self, **overrides):
        style = {
            "bg": BTN_BG, "fg": FG_HL,
            "activebackground": BTN_HOVER, "activeforeground": FG_HL,
            "bd": 0, "relief": "flat", "font": (FONT_MAIN, 10),
            "cursor": "hand2", "padx": 14, "pady": 8,
        }
        style.update(overrides)
        return style

    # -------------------------------------------------------------- HOME
    def show_home(self):
        self.clear_body()

        card = tk.Frame(self.body, bg=BG_SEC, padx=20, pady=20)
        card.pack(fill="x", pady=(10, 12))
        tk.Label(card, text="Reset Data", font=(FONT_MAIN, 13, "bold"), fg=FG_HL, bg=BG_SEC).pack(anchor="w")
        tk.Label(card, text="Wipe chosen data (users, guest data, keys, uploads, audio).\nArika stays installed and ready to use again.",
                 font=(FONT_MAIN, 9), fg=FG_NORM, bg=BG_SEC, justify="left").pack(anchor="w", pady=(4, 10))
        tk.Button(card, text="Open Reset Panel", command=self.show_reset, **self.btn_style()).pack(anchor="w")

        card2 = tk.Frame(self.body, bg=BG_SEC, padx=20, pady=20)
        card2.pack(fill="x", pady=(0, 12))
        tk.Label(card2, text="Uninstall Arika", font=(FONT_MAIN, 13, "bold"), fg=FG_HL, bg=BG_SEC).pack(anchor="w")
        tk.Label(card2, text="Deletes the entire Arika project folder from this PC.\nYou'll be asked exactly what to remove first.",
                 font=(FONT_MAIN, 9), fg=FG_NORM, bg=BG_SEC, justify="left").pack(anchor="w", pady=(4, 10))
        tk.Button(card2, text="Open Uninstall Panel", command=self.show_uninstall, **self.btn_style(bg="#45253a", activebackground="#5a2f4a")).pack(anchor="w")

        tk.Label(self.body, text=f"Project folder: {PROJECT_DIR}", font=(FONT_MAIN, 8), fg="#6c7086", bg=BG_MAIN).pack(anchor="w", pady=(6, 0))

    # ------------------------------------------------------------- RESET
    def show_reset(self):
        self.clear_body()

        tk.Button(self.body, text="< Back", command=self.show_home, **self.btn_style(padx=8, pady=4)).pack(anchor="w", pady=(0, 10))

        tk.Label(self.body, text="Choose what to delete:", font=(FONT_MAIN, 11, "bold"), fg=FG_HL, bg=BG_MAIN).pack(anchor="w")

        list_frame = tk.Frame(self.body, bg=BG_SEC, padx=12, pady=10)
        list_frame.pack(fill="x", pady=(8, 10))

        self.reset_vars = []
        self.targets = reset_targets()
        for t in self.targets:
            var = tk.BooleanVar(value=t["default"])
            cb = tk.Checkbutton(
                list_frame, text=t["label"], variable=var,
                font=(FONT_MAIN, 9), fg=FG_NORM, bg=BG_SEC,
                selectcolor=BG_SEC, activebackground=BG_SEC, activeforeground=FG_HL,
                anchor="w", justify="left", wraplength=560,
            )
            cb.pack(anchor="w", pady=3)
            self.reset_vars.append(var)

        sel_frame = tk.Frame(self.body, bg=BG_MAIN)
        sel_frame.pack(fill="x", pady=(0, 10))
        tk.Button(sel_frame, text="Select All", command=lambda: [v.set(True) for v in self.reset_vars], **self.btn_style(padx=8, pady=4)).pack(side="left", padx=(0, 8))
        tk.Button(sel_frame, text="Select None", command=lambda: [v.set(False) for v in self.reset_vars], **self.btn_style(padx=8, pady=4)).pack(side="left")

        self.reset_action_btn = tk.Button(self.body, text="Reset Selected Data", command=self.confirm_reset, **self.btn_style(bg="#45253a", activebackground="#5a2f4a"))
        self.reset_action_btn.pack(anchor="w", pady=(0, 10))

        self.reset_log = self.make_log_area()

    def confirm_reset(self):
        chosen = [t for t, v in zip(self.targets, self.reset_vars) if v.get()]
        if not chosen:
            messagebox.showinfo("Nothing selected", "Pick at least one item to reset.")
            return
        names = "\n".join(f"  • {t['label']}" for t in chosen)
        if not messagebox.askyesno(
            "Confirm Reset",
            f"This will permanently delete:\n\n{names}\n\nThis cannot be undone. Continue?",
        ):
            return
        if not messagebox.askyesno("Are you sure?", "Last check — really delete the selected data now?"):
            return
        self.reset_action_btn.configure(state="disabled")
        self.run_reset(chosen)

    def run_reset(self, chosen):
        self.log(self.reset_log, "Starting reset...\n")
        for t in chosen:
            paths = t["path"] if isinstance(t["path"], list) else [t["path"]]
            for p in paths:
                try:
                    if t["is_dir"]:
                        if p.exists():
                            shutil.rmtree(p)
                        p.mkdir(parents=True, exist_ok=True)
                        (p / ".gitkeep").touch()
                        self.log(self.reset_log, f"[OK] Cleared folder: {p}")
                    else:
                        if p.exists():
                            p.unlink()
                            self.log(self.reset_log, f"[OK] Deleted file: {p}")
                        else:
                            self.log(self.reset_log, f"[SKIP] Not found: {p}")
                except Exception as exc:
                    self.log(self.reset_log, f"[ERROR] {p}: {exc}")
        self.log(self.reset_log, "\nReset complete. Arika is still installed — just run it again like normal.")
        self.reset_action_btn.configure(state="normal")

    # --------------------------------------------------------- UNINSTALL
    def show_uninstall(self):
        self.clear_body()

        tk.Button(self.body, text="< Back", command=self.show_home, **self.btn_style(padx=8, pady=4)).pack(anchor="w", pady=(0, 10))

        tk.Label(self.body, text="What should be removed?", font=(FONT_MAIN, 11, "bold"), fg=FG_HL, bg=BG_MAIN).pack(anchor="w")

        opt_frame = tk.Frame(self.body, bg=BG_SEC, padx=12, pady=12)
        opt_frame.pack(fill="x", pady=(8, 10))

        self.uninstall_mode = tk.StringVar(value="project_only")
        tk.Radiobutton(
            opt_frame, text="Delete project files only\n(Python packages & Node.js stay installed on this PC — nothing else is touched)",
            variable=self.uninstall_mode, value="project_only",
            font=(FONT_MAIN, 9), fg=FG_NORM, bg=BG_SEC, selectcolor=BG_SEC,
            activebackground=BG_SEC, activeforeground=FG_HL, justify="left", wraplength=560, anchor="w",
        ).pack(anchor="w", pady=(0, 8))
        tk.Radiobutton(
            opt_frame, text="Delete everything\n(project files, AND best-effort 'pip uninstall' of the packages in requirements.txt)",
            variable=self.uninstall_mode, value="everything",
            font=(FONT_MAIN, 9), fg=FG_NORM, bg=BG_SEC, selectcolor=BG_SEC,
            activebackground=BG_SEC, activeforeground=FG_HL, justify="left", wraplength=560, anchor="w",
        ).pack(anchor="w")

        self.remove_shortcut_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            self.body, text=f"Also remove the desktop shortcut ({SHORTCUT_PATH.name})",
            variable=self.remove_shortcut_var, font=(FONT_MAIN, 9), fg=FG_NORM, bg=BG_MAIN,
            selectcolor=BG_MAIN, activebackground=BG_MAIN, activeforeground=FG_HL,
        ).pack(anchor="w", pady=(0, 10))

        tk.Label(
            self.body,
            text=f"Note: this will delete the ENTIRE folder:\n{PROJECT_DIR}\nincluding this maintenance tool itself.",
            font=(FONT_MAIN, 9), fg=FG_WARN, bg=BG_MAIN, justify="left",
        ).pack(anchor="w", pady=(0, 10))

        self.uninstall_action_btn = tk.Button(self.body, text="Uninstall Arika", command=self.confirm_uninstall, **self.btn_style(bg="#45253a", activebackground="#5a2f4a"))
        self.uninstall_action_btn.pack(anchor="w", pady=(0, 10))

        self.uninstall_log = self.make_log_area()

    def confirm_uninstall(self):
        mode = self.uninstall_mode.get()
        extra = " and uninstall pip packages from requirements.txt" if mode == "everything" else ""
        if not messagebox.askyesno(
            "Confirm Uninstall",
            f"This will permanently delete the whole project folder:\n\n{PROJECT_DIR}{extra}\n\nThis cannot be undone. Continue?",
        ):
            return
        confirm = messagebox.askyesno("Final confirmation", "Really uninstall Arika now? This closes the app and cannot be reversed.")
        if not confirm:
            return
        self.uninstall_action_btn.configure(state="disabled")
        self.run_uninstall(mode)

    def run_uninstall(self, mode):
        self.log(self.uninstall_log, "Preparing uninstall...")

        if mode == "everything" and REQUIREMENTS_FILE.exists():
            self.log(self.uninstall_log, "Uninstalling Python packages from requirements.txt (best effort)...")
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "uninstall", "-y", "-r", str(REQUIREMENTS_FILE)],
                    capture_output=True, text=True, shell=False,
                )
                if result.stdout:
                    self.log(self.uninstall_log, result.stdout.strip())
                if result.stderr:
                    self.log(self.uninstall_log, result.stderr.strip())
            except Exception as exc:
                self.log(self.uninstall_log, f"[WARN] pip uninstall failed: {exc}")

        if self.remove_shortcut_var.get() and SHORTCUT_PATH.exists():
            try:
                SHORTCUT_PATH.unlink()
                self.log(self.uninstall_log, f"[OK] Removed desktop shortcut: {SHORTCUT_PATH}")
            except Exception as exc:
                self.log(self.uninstall_log, f"[WARN] Could not remove shortcut: {exc}")

        self.log(self.uninstall_log, "Handing off to cleanup script and closing Arika Maintenance...")
        try:
            self.schedule_self_delete()
        except Exception:
            self.log(self.uninstall_log, traceback.format_exc())
            messagebox.showerror("Error", "Could not schedule folder deletion. See log for details.")
            self.uninstall_action_btn.configure(state="normal")
            return

        self.root.after(1200, self.root.destroy)

    def schedule_self_delete(self):
        """Windows can't delete a running program's own folder, so we write
        a tiny .bat to %TEMP% that waits for this process to exit, then
        removes the whole project folder, then deletes itself."""
        pid = os.getpid()
        bat_path = Path(tempfile.gettempdir()) / "arika_uninstall_cleanup.bat"
        bat_content = f'''@echo off
:waitloop
tasklist /FI "PID eq {pid}" 2>NUL | find "{pid}" >NUL
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto waitloop
)
timeout /t 1 /nobreak >nul
rmdir /s /q "{PROJECT_DIR}"
del "%~f0"
'''
        bat_path.write_text(bat_content, encoding="utf-8")
        subprocess.Popen(
            ["cmd", "/c", str(bat_path)],
            creationflags=subprocess.CREATE_NO_WINDOW,
            close_fds=True,
        )

    # ----------------------------------------------------------- helpers
    def make_log_area(self):
        tk.Label(self.body, text="Log:", font=(FONT_MAIN, 9, "bold"), fg=FG_NORM, bg=BG_MAIN).pack(anchor="w")
        from tkinter.scrolledtext import ScrolledText
        area = ScrolledText(self.body, height=8, state="disabled", font=("Consolas", 9), bg=BG_SEC, fg=FG_HL, insertbackground=FG_HL, bd=0, padx=10, pady=10)
        area.pack(fill="both", expand=True)
        return area

    def log(self, area, message):
        area.configure(state="normal")
        area.insert("end", message + "\n")
        area.see("end")
        area.configure(state="disabled")
        area.update_idletasks()


if __name__ == "__main__":
    if not sys.platform.startswith("win"):
        print("This tool uses Windows-specific steps (shortcut removal, self-cleanup .bat).")
        print("It will still reset/delete files, but run it on the same Windows PC Arika is installed on.")

    root = tk.Tk()
    app = MaintenanceApp(root)
    root.mainloop()
