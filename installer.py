import os
import sys
import subprocess
import traceback
from pathlib import Path
import threading
import tkinter as tk
from tkinter import messagebox
from tkinter.scrolledtext import ScrolledText

# Make UI crisp but we'll use a smaller base resolution so it doesn't look huge
try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

PROJECT_DIR = Path(__file__).resolve().parent

# Smart Desktop Path Detection (OneDrive fix)
USER_HOME = Path(os.path.expanduser("~"))
if (USER_HOME / "OneDrive" / "Desktop").exists():
    DESKTOP_DIR = USER_HOME / "OneDrive" / "Desktop"
else:
    DESKTOP_DIR = USER_HOME / "Desktop"

RUN_BAT = PROJECT_DIR / "run_arika.bat"
SHORTCUT_PATH = DESKTOP_DIR / "Arika AI.lnk"
REQUIREMENTS_FILE = PROJECT_DIR / "requirements.txt"
MINECRAFT_BOT_DIR = PROJECT_DIR / "minecraft_bot"

# --- Premium Midnight Theme Colors ---
BG_MAIN = "#11111b"       # Deep midnight dark
BG_SEC = "#1e1e2e"        # Slightly lighter card background
FG_NORM = "#bac2de"       # Soft bluish-grey for readable text
FG_HL = "#cdd6f4"         # Crisp white for main text
FG_ACCENT = "#89b4fa"     # Cool blue accent for active steps
FG_SUCCESS = "#a6e3a1"    # Soft green for completed steps
FG_ERROR = "#f38ba8"      # Soft red for errors
BTN_BG = "#313244"        # Button background
BTN_HOVER = "#45475a"     # Button hover state
FONT_MAIN = "Segoe UI"

def log(message: str):
    def _append():
        try:
            text_area.configure(state="normal")
            text_area.insert("end", message + "\n")
            text_area.see("end")
            text_area.configure(state="disabled")
        except Exception:
            pass
    try:
        root.after(0, _append)
    except Exception:
        try:
            print(message)
        except Exception:
            pass

def run_command(cmd, check=True):
    log(f"> {' '.join(cmd) if isinstance(cmd, list) else cmd}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, shell=False)
        if result.stdout:
            log(result.stdout.strip())
        if result.stderr:
            log(result.stderr.strip())
        if check and result.returncode != 0:
            raise subprocess.CalledProcessError(result.returncode, cmd)
        return result.returncode == 0
    except Exception as exc:
        log(f"Command failed: {exc}")
        return False

def create_run_bat():
    log("Creating run_arika.bat...")
    content = """@echo off
cd /d "%~dp0"
echo Starting Arika...
py -3 main.py || python main.py
pause
"""
    RUN_BAT.write_text(content, encoding="utf-8")
    log(f"Created: {RUN_BAT}")

def install_requirements():
    if not REQUIREMENTS_FILE.exists():
        log("Error: requirements.txt not found.")
        root.after(0, lambda: messagebox.showerror("Error", "requirements.txt not found."))
        return False

    try:
        log("Upgrading pip...")
        subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"], check=True, capture_output=True)
        log("Installing required Python packages...")
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)], check=True, capture_output=True)
        log("Package installation complete.")
        return True
    except subprocess.CalledProcessError as exc:
        log(f"Installation error: {exc}")
        root.after(0, lambda: messagebox.showerror("Error", "Failed to install Python dependencies. See the log for details."))
        return False

def _command_exists(name):
    from shutil import which
    return which(name) is not None


def ensure_node():
    """Make sure Node.js (+ npm) is on PATH. Needed for minecraft_bot/bot.js
    (mineflayer) — Arika's Minecraft reflex layer. Tries winget first (same
    approach scripts/ensure_python_and_run.ps1 uses for Python), falls back
    to just telling the Admin where to grab the installer manually."""
    if _command_exists("node") and _command_exists("npm"):
        log("Node.js already installed.")
        return True

    log("Node.js not found. Attempting install via winget...")
    if _command_exists("winget"):
        ok = run_command([
            "winget", "install", "--exact", "--id", "OpenJS.NodeJS.LTS",
            "-e", "--accept-package-agreements", "--accept-source-agreements",
        ], check=False)
        if ok and _command_exists("node"):
            log("Node.js installed via winget.")
            return True

    log("Could not auto-install Node.js. Please install it manually from "
        "https://nodejs.org (LTS version), then re-run setup.bat so the "
        "Minecraft bot dependencies can be installed.")
    return False


def install_minecraft_bot_deps():
    """npm install inside minecraft_bot/ — mineflayer, pathfinder, pvp,
    auto-eat, express. Skipped gracefully if Node isn't available; Arika's
    normal chat features still work fine without this, only Minecraft
    mode needs it."""
    if not MINECRAFT_BOT_DIR.exists():
        log("minecraft_bot folder not found, skipping bot dependency install.")
        return False

    if not (_command_exists("npm")):
        log("npm not available, skipping Minecraft bot dependency install.")
        return False

    log("Installing Minecraft bot dependencies (npm install)... this can take a minute.")
    try:
        result = subprocess.run(
            ["npm", "install"], cwd=str(MINECRAFT_BOT_DIR),
            capture_output=True, text=True, shell=False,
        )
        if result.stdout:
            log(result.stdout.strip())
        if result.stderr:
            log(result.stderr.strip())
        if result.returncode != 0:
            log("npm install reported errors — see log above. Minecraft mode "
                "may not work until this is fixed (you can re-run "
                "`npm install` inside minecraft_bot manually).")
            return False
        log("Minecraft bot dependencies installed.")
        return True
    except FileNotFoundError:
        log("npm not found on PATH even after Node.js check — skipping.")
        return False
    except Exception as exc:
        log(f"npm install failed: {exc}")
        return False


def check_java_and_tlauncher():
    """Java is required to actually run Minecraft/TLauncher itself (this
    only affects the Admin's TLauncher game client, not Arika's bot — the
    bot connects over the network protocol and doesn't need Java). Best
    effort: detect Java, detect a common TLauncher install path, and if
    TLauncher isn't found, open its official download page so the Admin
    can grab it (never installed silently/without the Admin seeing the
    installer — TLauncher is third-party software)."""
    has_java = _command_exists("java")
    log(f"Java on PATH: {'yes' if has_java else 'no'}")
    if not has_java:
        log("Java not found. Minecraft/TLauncher itself needs Java to run. "
            "Attempting install via winget (Eclipse Temurin)...")
        if _command_exists("winget"):
            run_command([
                "winget", "install", "--exact", "--id", "EclipseAdoptium.Temurin.17.JRE",
                "-e", "--accept-package-agreements", "--accept-source-agreements",
            ], check=False)
        if not _command_exists("java"):
            log("Could not confirm Java install — if TLauncher fails to "
                "open later, install Java manually from https://adoptium.net")

    common_paths = [
        Path(os.environ.get("APPDATA", "")) / "TLauncher",
        Path(os.environ.get("LOCALAPPDATA", "")) / "TLauncher",
        DESKTOP_DIR.parent / "TLauncher",
    ]
    tlauncher_found = any(p.exists() for p in common_paths if str(p))
    log(f"TLauncher install detected: {'yes' if tlauncher_found else 'no'}")
    if not tlauncher_found:
        log("TLauncher not detected on this PC. Opening the official "
            "download page (tlauncher.org) so you can install it yourself — "
            "Arika won't silently install third-party launcher software.")
        try:
            import webbrowser
            webbrowser.open("https://tlauncher.org/en/")
        except Exception as exc:
            log(f"Couldn't open browser automatically: {exc}. "
                "Please visit https://tlauncher.org/en/ manually.")
    return has_java, tlauncher_found


def create_shortcut():
    log(f"Creating desktop shortcut at {SHORTCUT_PATH}...")
    target_path = str(RUN_BAT).replace("'", "''")
    working_dir = str(PROJECT_DIR).replace("'", "''")
    icon_path = str(sys.executable).replace("'", "''")

    ps_script = (
        "$WshShell = New-Object -ComObject WScript.Shell;"
        f"$Shortcut = $WshShell.CreateShortcut('{SHORTCUT_PATH}');"
        f"$Shortcut.TargetPath = '{target_path}';"
        f"$Shortcut.WorkingDirectory = '{working_dir}';"
        f"$Shortcut.WindowStyle = 1;"
        f"$Shortcut.IconLocation = '{icon_path},0';"
        "$Shortcut.Save();"
    )

    if run_command(["powershell", "-NoProfile", "-Command", ps_script]):
        log("Desktop shortcut created.")
        return True
    else:
        log("Failed to create desktop shortcut via PowerShell.")
        root.after(0, lambda: messagebox.showerror("Error", "could not creat desktop icon powershell not avalible"))
        return False

def open_project_folder():
    path = str(PROJECT_DIR)
    log(f"Opening folder: {path}")
    if sys.platform.startswith("win"):
        subprocess.Popen(["explorer", path])
    else:
        messagebox.showinfo("Info", f"Open the folder manually: {path}")

def on_close():
    root.destroy()

# --- GUI Setup ---
root = tk.Tk()
root.title("Arika Setup")
root.geometry("650x520")  # Compact size!
root.resizable(False, False)
root.configure(bg=BG_MAIN)

# Main padding frame
frame = tk.Frame(root, padx=25, pady=20, bg=BG_MAIN)
frame.pack(fill="both", expand=True)

header = tk.Label(frame, text="Arika AI Setup", font=(FONT_MAIN, 20, "bold"), fg=FG_ACCENT, bg=BG_MAIN)
header.pack(anchor="w")

subtitle = tk.Label(frame, text="Automated initialization sequence. Relax and let it run.", font=(FONT_MAIN, 10), fg=FG_NORM, bg=BG_MAIN)
subtitle.pack(anchor="w", pady=(0, 16))

# --- Steps Tracker UI ---
steps_frame = tk.Frame(frame, bg=BG_SEC, padx=15, pady=15)
steps_frame.pack(fill="x", pady=(0, 16))

step_labels = []
for i, text in enumerate([
    "Step 1: Create Run Script",
    "Step 2: Install Dependencies",
    "Step 3: Minecraft Bot Setup",
    "Step 4: Create Desktop Shortcut",
]):
    lbl = tk.Label(steps_frame, text=f"◯  {text}", font=(FONT_MAIN, 10), fg=FG_NORM, bg=BG_SEC)
    lbl.pack(anchor="w", pady=2)
    step_labels.append(lbl)

def update_step_ui(step_index, text, color):
    def _update():
        step_labels[step_index].configure(text=text, fg=color)
    root.after(0, _update)

# --- Action Buttons ---
button_frame = tk.Frame(frame, bg=BG_MAIN)
button_frame.pack(fill="x", pady=(0, 16))

btn_style = {
    "bg": BTN_BG, "fg": FG_HL, 
    "activebackground": BTN_HOVER, "activeforeground": FG_HL, 
    "bd": 0, "relief": "flat", "font": (FONT_MAIN, 9),
    "cursor": "hand2", "padx": 10, "pady": 4
}

open_folder_btn = tk.Button(button_frame, text="Open Project Folder", width=20, command=open_project_folder, **btn_style, state="disabled")
open_folder_btn.pack(side="left", padx=(0, 10))

close_btn = tk.Button(button_frame, text="Close Installer", width=20, command=on_close, **btn_style, state="disabled")
close_btn.pack(side="left")

# --- Log UI ---
log_label = tk.Label(frame, text="Console Output:", font=(FONT_MAIN, 10, "bold"), fg=FG_NORM, bg=BG_MAIN)
log_label.pack(anchor="w", pady=(0, 4))

text_area = ScrolledText(frame, height=10, state="disabled", font=("Consolas", 9), bg=BG_SEC, fg=FG_HL, insertbackground=FG_HL, bd=0, padx=10, pady=10)
text_area.pack(fill="both", expand=True)

# --- Automation Logic ---
def run_automatic_setup():
    def worker():
        try:
            # Step 1
            update_step_ui(0, "●  Step 1: Creating Run Script...", FG_ACCENT)
            create_run_bat()
            update_step_ui(0, "✓  Step 1: Run Script Created", FG_SUCCESS)

            # Step 2
            update_step_ui(1, "●  Step 2: Installing Dependencies... (This may take a while)", FG_ACCENT)
            success_deps = install_requirements()
            if success_deps:
                update_step_ui(1, "✓  Step 2: Dependencies Installed", FG_SUCCESS)
            else:
                update_step_ui(1, "✗  Step 2: Dependency Install Failed", FG_ERROR)

            # Step 3 — Minecraft bot setup (Node.js + npm deps + Java/TLauncher check)
            update_step_ui(2, "●  Step 3: Minecraft Bot Setup... (Node.js + npm packages)", FG_ACCENT)
            node_ok = ensure_node()
            bot_deps_ok = install_minecraft_bot_deps() if node_ok else False
            check_java_and_tlauncher()
            if node_ok and bot_deps_ok:
                update_step_ui(2, "✓  Step 3: Minecraft Bot Ready", FG_SUCCESS)
            elif node_ok:
                update_step_ui(2, "✗  Step 3: Minecraft Bot Deps Failed (see log)", FG_ERROR)
            else:
                update_step_ui(2, "✗  Step 3: Node.js Missing (install manually)", FG_ERROR)

            # Step 4
            update_step_ui(3, "●  Step 4: Creating Desktop Shortcut...", FG_ACCENT)
            success_shortcut = create_shortcut()
            if success_shortcut:
                update_step_ui(3, "✓  Step 4: Desktop Shortcut Created", FG_SUCCESS)
            else:
                update_step_ui(3, "✗  Step 4: Shortcut Creation Failed", FG_ERROR)

            log("\n--- Setup Complete! ---")
            log("If TLauncher wasn't detected, finish installing it from the page "
                "that just opened, then log in there like normal — Arika's bot "
                "connects to the world over the network, it doesn't need TLauncher "
                "itself running.")
            log("You can safely close this window now.")

        except Exception as e:
            log(traceback.format_exc())
            root.after(0, lambda: messagebox.showerror("Error", "Automatic setup failed. See the log for details."))
        finally:
            # Enable buttons when done
            root.after(0, lambda: open_folder_btn.configure(state="normal"))
            root.after(0, lambda: close_btn.configure(state="normal"))

    # Start logic in background thread
    t = threading.Thread(target=worker, daemon=True)
    t.start()

log("Initializing Arika Automated Setup...")
root.after(800, run_automatic_setup)  # Slight delay for UI to render before starting

root.protocol("WM_DELETE_WINDOW", on_close)
root.mainloop()