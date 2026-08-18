"""
Automation actions
==================
Actual OS-level actions Arika can perform. Windows-first (matches your
run_arika.bat / setup.bat launcher setup), with basic macOS/Linux fallbacks.

Each function either returns a short human-readable result string, or raises
an Exception with a clear message. command_router.py is responsible for
catching exceptions and recording them in task_manager.

Extend APP_ALIASES as you find more apps you want Arika to open by name.
"""

import os
import platform
import subprocess
import urllib.parse
import webbrowser
from datetime import datetime

SYSTEM = platform.system()  # "Windows", "Darwin", "Linux"

# Friendly name -> actual launch target. Add more as needed.
APP_ALIASES = {
    "chrome": "chrome",
    "notepad": "notepad",
    "vscode": "code",
    "vs code": "code",
    "explorer": "explorer",
    "file explorer": "explorer",
    "files": "explorer",
    "calculator": "calc",
    "calc": "calc",
    "spotify": "spotify",
    "whatsapp": "whatsapp",
    "settings": "ms-settings:",
}


def open_app(name: str) -> str:
    name_key = (name or "").strip().lower()
    target = APP_ALIASES.get(name_key, name_key)

    if SYSTEM == "Windows":
        # 'start ""' avoids issues when the target path has spaces.
        subprocess.Popen(f'start "" "{target}"', shell=True)
    elif SYSTEM == "Darwin":
        subprocess.Popen(["open", "-a", target])
    else:
        subprocess.Popen([target])

    return f"Opened app: {name}"


def open_website(url: str) -> str:
    url = (url or "").strip()
    if not url:
        raise ValueError("No URL given")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    webbrowser.open(url)
    return f"Opened website: {url}"


def play_media(query: str, service: str = "youtube") -> str:
    """There's no single universal 'press play on this song' API without
    integrating each service's SDK (e.g. Spotify Web API + OAuth for real
    playback control). The reliable, zero-setup version: open the service
    with the song pre-searched, so it's one click away.

    TODO (future upgrade): wire up Spotify Web API with a saved token to
    actually start playback instead of just searching.
    """
    if not query:
        raise ValueError("No song/video name given")

    service = (service or "youtube").lower()
    encoded = urllib.parse.quote(query)

    if service == "spotify":
        url = f"https://open.spotify.com/search/{encoded}"
    else:
        url = f"https://www.youtube.com/results?search_query={encoded}"

    webbrowser.open(url)
    return f"Opened {service} search for: {query}"


def create_folder(path: str) -> str:
    path = os.path.expanduser((path or "").strip())
    if not path:
        raise ValueError("No folder path given")
    try:
        os.makedirs(path, exist_ok=True)
    except PermissionError:
        raise PermissionError(
            f"Access denied creating '{path}'. This usually means the path "
            f"doesn't actually exist on this PC (e.g. a guessed username) or "
            f"needs admin rights. Use '~' for the home directory instead of "
            f"a hardcoded 'C:/Users/<name>' path."
        )
    return f"Folder created: {path}"


def create_file(path: str, content: str = "") -> str:
    path = os.path.expanduser((path or "").strip())
    if not path:
        raise ValueError("No file path given")
    folder = os.path.dirname(path)
    try:
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content or "")
    except PermissionError:
        raise PermissionError(
            f"Access denied creating '{path}'. This usually means the path "
            f"doesn't actually exist on this PC (e.g. a guessed username) or "
            f"needs admin rights. Use '~' for the home directory instead of "
            f"a hardcoded 'C:/Users/<name>' path."
        )
    return f"File created: {path}"


def take_screenshot(save_dir: str) -> str:
    try:
        import pyautogui
    except ImportError:
        raise RuntimeError(
            "pyautogui not installed. Run: pip install pyautogui pillow"
        )

    os.makedirs(save_dir, exist_ok=True)
    filename = f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    path = os.path.join(save_dir, filename)
    img = pyautogui.screenshot()
    img.save(path)
    return path


# ---------------------------------------------------------------------------
# Windows virtual-key codes for media/volume keys. These are simulated via
# ctypes keybd_event — this works for ANY currently-playing media app
# (Spotify, YouTube tab, VLC...) because it's the same signal a physical
# keyboard's media keys send, unlike a Spotify-only API integration.
# ---------------------------------------------------------------------------
_VK_VOLUME_MUTE = 0xAD
_VK_VOLUME_DOWN = 0xAE
_VK_VOLUME_UP = 0xAF
_VK_MEDIA_NEXT_TRACK = 0xB0
_VK_MEDIA_PREV_TRACK = 0xB1
_VK_MEDIA_PLAY_PAUSE = 0xB3


def _press_virtual_key(vk_code: int):
    if SYSTEM != "Windows":
        raise RuntimeError("Media/volume key simulation is Windows-only right now.")
    import ctypes
    KEYEVENTF_KEYUP = 0x0002
    ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
    ctypes.windll.user32.keybd_event(vk_code, 0, KEYEVENTF_KEYUP, 0)


def volume_control(direction: str) -> str:
    """direction: 'up', 'down', or 'mute'. Each 'up'/'down' press is one
    small step (same as a physical key press) — call it a few times in a
    row for a bigger jump."""
    direction = (direction or "").strip().lower()
    mapping = {
        "up": _VK_VOLUME_UP,
        "down": _VK_VOLUME_DOWN,
        "mute": _VK_VOLUME_MUTE,
    }
    if direction not in mapping:
        raise ValueError("direction must be 'up', 'down', or 'mute'")
    _press_virtual_key(mapping[direction])
    return f"Volume: {direction}"


def media_control(action: str) -> str:
    """action: 'play_pause', 'next', or 'previous'. Controls whatever media
    app currently has focus/is playing (Spotify, YouTube tab, VLC, etc.) —
    no per-service API/OAuth needed."""
    action = (action or "").strip().lower()
    mapping = {
        "play_pause": _VK_MEDIA_PLAY_PAUSE,
        "next": _VK_MEDIA_NEXT_TRACK,
        "previous": _VK_MEDIA_PREV_TRACK,
    }
    if action not in mapping:
        raise ValueError("action must be 'play_pause', 'next', or 'previous'")
    _press_virtual_key(mapping[action])
    return f"Media: {action}"


def play_on_youtube(query: str) -> str:
    """Unlike play_media (which just opens a search page), this actually
    auto-plays the first YouTube result via pywhatkit — closer to real
    'press play' behaviour."""
    if not query:
        raise ValueError("No song/video name given")
    try:
        import pywhatkit
    except ImportError:
        raise RuntimeError("pywhatkit not installed. Run: pip install pywhatkit")

    pywhatkit.playonyt(query)
    return f"Now playing on YouTube: {query}"


def set_brightness(level: int) -> str:
    """level: 0-100."""
    try:
        import screen_brightness_control as sbc
    except ImportError:
        raise RuntimeError(
            "screen-brightness-control not installed. "
            "Run: pip install screen-brightness-control"
        )
    level = max(0, min(100, int(level)))
    sbc.set_brightness(level)
    return f"Brightness set to {level}%"


def get_clipboard() -> str:
    try:
        import pyperclip
    except ImportError:
        raise RuntimeError("pyperclip not installed. Run: pip install pyperclip")
    text = pyperclip.paste()
    return text if text else "(clipboard is empty)"


def set_clipboard(text: str) -> str:
    try:
        import pyperclip
    except ImportError:
        raise RuntimeError("pyperclip not installed. Run: pip install pyperclip")
    pyperclip.copy(text or "")
    return f"Copied to clipboard: {text[:60]}"


def lock_screen() -> str:
    if SYSTEM != "Windows":
        raise RuntimeError("lock_screen is Windows-only right now.")
    import ctypes
    ctypes.windll.user32.LockWorkStation()
    return "Screen locked"


def system_power(action: str, confirm: bool = False) -> str:
    """action: 'shutdown', 'restart', or 'sleep'. Destructive — requires
    confirm=True, which command_router only sets after the Admin has
    explicitly confirmed in chat (see system_instruction.txt rules)."""
    action = (action or "").strip().lower()
    if action not in ("shutdown", "restart", "sleep"):
        raise ValueError("action must be 'shutdown', 'restart', or 'sleep'")
    if not confirm:
        raise ValueError(
            f"'{action}' needs explicit confirmation before it runs — ask the "
            f"Admin to confirm first."
        )

    if SYSTEM == "Windows":
        if action == "shutdown":
            subprocess.Popen("shutdown /s /t 30", shell=True)
            return "Shutting down in 30 seconds. Run 'shutdown /a' to cancel."
        elif action == "restart":
            subprocess.Popen("shutdown /r /t 30", shell=True)
            return "Restarting in 30 seconds. Run 'shutdown /a' to cancel."
        else:
            subprocess.Popen("rundll32.exe powrprof.dll,SetSuspendState 0,1,0", shell=True)
            return "Going to sleep."
    else:
        raise RuntimeError("system_power is Windows-only right now.")


def system_info() -> dict:
    try:
        import psutil
    except ImportError:
        raise RuntimeError("psutil not installed. Run: pip install psutil")

    battery = psutil.sensors_battery()
    info = {
        "cpu_percent": psutil.cpu_percent(interval=0.5),
        "ram_percent": psutil.virtual_memory().percent,
        "battery_percent": battery.percent if battery else None,
        "battery_plugged_in": battery.power_plugged if battery else None,
    }
    return info


def open_folder(path: str) -> str:
    path = os.path.expanduser((path or "").strip())
    if not path:
        raise ValueError("No folder path given")
    if not os.path.isdir(path):
        raise FileNotFoundError(f"Folder does not exist: {path}")

    if SYSTEM == "Windows":
        os.startfile(path)
    elif SYSTEM == "Darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])
    return f"Opened folder: {path}"


def list_open_windows() -> list:
    try:
        import pygetwindow as gw
    except ImportError:
        raise RuntimeError("pygetwindow not installed. Run: pip install pygetwindow")

    titles = [t for t in gw.getAllTitles() if t.strip()]
    return titles


def close_app(name: str) -> str:
    """Kills all processes whose name contains `name` (case-insensitive)."""
    try:
        import psutil
    except ImportError:
        raise RuntimeError("psutil not installed. Run: pip install psutil")

    name_key = (name or "").strip().lower()
    if not name_key:
        raise ValueError("No app name given")

    killed = []
    for proc in psutil.process_iter(["name"]):
        proc_name = (proc.info.get("name") or "").lower()
        if name_key in proc_name:
            try:
                proc.terminate()
                killed.append(proc.info["name"])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    if not killed:
        raise RuntimeError(f"No running process matching '{name}' found.")
    return f"Closed: {', '.join(set(killed))}"


def delete_path(path: str, confirm: bool = False) -> str:
    """Sends a file/folder to the Recycle Bin (NOT permanent delete) via
    send2trash — recoverable if the Admin changes their mind. Requires
    confirm=True (see system_instruction.txt rules)."""
    path = os.path.expanduser((path or "").strip())
    if not path:
        raise ValueError("No path given")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Path does not exist: {path}")
    if not confirm:
        raise ValueError(
            "Deleting needs explicit confirmation before it runs — ask the "
            "Admin to confirm first."
        )

    try:
        from send2trash import send2trash
    except ImportError:
        raise RuntimeError("send2trash not installed. Run: pip install send2trash")

    send2trash(path)
    return f"Moved to Recycle Bin: {path}"


def send_whatsapp_message(phone: str, message: str) -> str:
    """Opens WhatsApp Web and sends instantly. NOTE: this is genuinely a
    bit fragile — it depends on WhatsApp Web already being logged in on
    this machine's default browser, and timing quirks can occasionally
    misfire. Treat it as 'usually works', not 'always works'."""
    try:
        import pywhatkit
    except ImportError:
        raise RuntimeError("pywhatkit not installed. Run: pip install pywhatkit")

    phone = (phone or "").strip()
    if not phone.startswith("+"):
        raise ValueError("Phone number must include country code, e.g. +91XXXXXXXXXX")
    if not message:
        raise ValueError("No message given")

    pywhatkit.sendwhatmsg_instantly(phone, message, wait_time=15, tab_close=True)
    return f"WhatsApp message sent to {phone}"


def open_web_search(query: str) -> str:
    """Opens a Google search for `query` in the default browser."""
    query = (query or "").strip()
    if not query:
        raise ValueError("No search query given")
    url = "https://www.google.com/search?q=" + urllib.parse.quote(query)
    webbrowser.open(url)
    return f"Searched the web for: {query}"


def send_email(to: str, subject: str, body: str) -> str:
    """Sends an email via SMTP using credentials saved in Settings
    (email_address / email_app_password — for Gmail this must be an App
    Password, not the normal account password: myaccount.google.com/apppasswords).
    Uses Gmail's SMTP server; edit smtp_host/smtp_port below if you use a
    different provider."""
    from backend import settings_manager

    settings = settings_manager.load_settings()
    from_addr = (settings.get("email_address") or "").strip()
    app_password = (settings.get("email_app_password") or "").strip()
    if not from_addr or not app_password:
        raise RuntimeError(
            "No email account configured. Add email_address and "
            "email_app_password in Settings first."
        )

    to = (to or "").strip()
    if not to:
        raise ValueError("No recipient given")

    import smtplib
    from email.mime.text import MIMEText

    msg = MIMEText(body or "")
    msg["Subject"] = subject or "(no subject)"
    msg["From"] = from_addr
    msg["To"] = to

    smtp_host, smtp_port = "smtp.gmail.com", 465
    with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15) as server:
        server.login(from_addr, app_password)
        server.sendmail(from_addr, [to], msg.as_string())

    return f"Email sent to {to}"


def webcam_photo(save_dir: str) -> str:
    """Takes a photo with this PC's webcam (needs opencv-python:
    pip install opencv-python)."""
    try:
        import cv2
    except ImportError:
        raise RuntimeError("opencv-python not installed. Run: pip install opencv-python")

    os.makedirs(save_dir, exist_ok=True)
    cam = cv2.VideoCapture(0)
    try:
        if not cam.isOpened():
            raise RuntimeError("Could not access the webcam — is it in use by another app?")
        ok, frame = cam.read()
        if not ok:
            raise RuntimeError("Failed to capture a frame from the webcam.")
        filename = f"webcam_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        path = os.path.join(save_dir, filename)
        cv2.imwrite(path, frame)
        return path
    finally:
        cam.release()


def mic_mute(state: str) -> str:
    """Mute/unmute the default microphone. state: 'mute' or 'unmute'.
    Windows-only (needs pycaw + comtypes: pip install pycaw comtypes)."""
    state = (state or "").strip().lower()
    if state not in ("mute", "unmute"):
        raise ValueError("state must be 'mute' or 'unmute'")
    if SYSTEM != "Windows":
        raise RuntimeError("mic_mute is currently only implemented for Windows.")

    try:
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        from ctypes import cast, POINTER
    except ImportError:
        raise RuntimeError("pycaw/comtypes not installed. Run: pip install pycaw comtypes")

    mic = AudioUtilities.GetMicrophone()
    interface = mic.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    volume = cast(interface, POINTER(IAudioEndpointVolume))
    volume.SetMute(1 if state == "mute" else 0, None)
    return f"Microphone {state}d"


# In-memory reminders — cleared on restart. Good enough for "remind me in
# 20 minutes"-style asks; not a substitute for a real calendar/task app.
_pending_reminders = []


def set_reminder(text: str, seconds_from_now: int) -> str:
    """Schedules a reminder. When it fires, it's printed to the console
    (and, on Windows, also shown as a toast if `win10toast` is installed)
    — it does NOT speak through Arika's TTS or push into the chat, since
    the assistant may not be open in a browser when it fires."""
    import threading

    text = (text or "").strip()
    if not text:
        raise ValueError("No reminder text given")
    try:
        seconds_from_now = int(seconds_from_now)
    except (TypeError, ValueError):
        raise ValueError("seconds_from_now must be a number")
    if seconds_from_now <= 0:
        raise ValueError("seconds_from_now must be positive")

    def _fire():
        print(f"[Reminder] {text}")
        try:
            from win10toast import ToastNotifier
            ToastNotifier().show_toast("Arika reminder", text, duration=10, threaded=True)
        except ImportError:
            pass  # console print above is the guaranteed fallback

    timer = threading.Timer(seconds_from_now, _fire)
    timer.daemon = True
    timer.start()
    _pending_reminders.append({"text": text, "fires_in_seconds": seconds_from_now})
    return f"Reminder set for {seconds_from_now} seconds from now: {text}"


# Only scripts inside this folder can be run — never an arbitrary
# admin-supplied path. Keeps "run a script" from silently becoming
# "run any file on the system".
SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "automation_scripts")


def run_script(name: str, confirm: bool = False) -> str:
    """Runs a script by filename from the automation_scripts/ folder ONLY
    (create it in the project root and drop .py/.bat/.sh/.ps1 files there).
    Deliberately does not accept an arbitrary path — you decide what's
    runnable by what you put in that folder, not by what the AI is asked
    to run. Also requires confirm=True, same as delete_path/system_power,
    since a script can do anything the Admin's own account can do."""
    if not confirm:
        raise ValueError(
            "Running a script needs explicit confirmation before it runs "
            "— ask the Admin to confirm first."
        )

    name = os.path.basename((name or "").strip())
    if not name:
        raise ValueError("No script name given")

    os.makedirs(SCRIPTS_DIR, exist_ok=True)
    path = os.path.join(SCRIPTS_DIR, name)
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"'{name}' not found in automation_scripts/. Put the script "
            f"there first — arbitrary paths outside this folder aren't allowed."
        )

    ext = os.path.splitext(name)[1].lower()
    runners = {
        ".py": ["python", path],
        ".bat": [path],
        ".ps1": ["powershell", "-ExecutionPolicy", "Bypass", "-File", path],
        ".sh": ["bash", path],
    }
    cmd = runners.get(ext)
    if not cmd:
        raise ValueError(f"Unsupported script type '{ext}'. Use .py, .bat, .ps1, or .sh")

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    output = (result.stdout or "") + (result.stderr or "")
    return output.strip() or f"Ran {name} (no output)"


# ---------------------------------------------------------------------------
# Mouse + keyboard control (pyautogui). Full PC control — already gated to
# Admin-only by command_router, same as everything else in this file.
# pyautogui.FAILSAFE stays on (default): slamming the mouse into a screen
# corner aborts whatever's happening, as a manual panic button.
# ---------------------------------------------------------------------------

def _pyautogui():
    try:
        import pyautogui
    except ImportError:
        raise RuntimeError("pyautogui not installed. Run: pip install pyautogui")
    return pyautogui


def mouse_move(x: int, y: int, duration: float = 0.2) -> str:
    pg = _pyautogui()
    x, y = int(x), int(y)
    pg.moveTo(x, y, duration=max(0.0, float(duration)))
    return f"Mouse moved to ({x}, {y})"


def mouse_click(x: int = None, y: int = None, button: str = "left",
                 double: bool = False) -> str:
    """If x/y are omitted, clicks at the current mouse position instead of
    moving first."""
    pg = _pyautogui()
    button = (button or "left").strip().lower()
    if button not in ("left", "right", "middle"):
        raise ValueError("button must be 'left', 'right', or 'middle'")

    kwargs = {"button": button}
    if x is not None and y is not None:
        kwargs["x"], kwargs["y"] = int(x), int(y)

    if double:
        pg.doubleClick(**kwargs)
        return f"Double-clicked ({button}) at ({x}, {y})" if x is not None else f"Double-clicked ({button})"

    pg.click(**kwargs)
    return f"Clicked ({button}) at ({x}, {y})" if x is not None else f"Clicked ({button})"


def mouse_scroll(amount: int) -> str:
    """Positive amount scrolls up, negative scrolls down."""
    pg = _pyautogui()
    pg.scroll(int(amount))
    return f"Scrolled by {amount}"


def keyboard_type(text: str, interval: float = 0.02) -> str:
    pg = _pyautogui()
    text = text or ""
    if not text:
        raise ValueError("No text given to type")
    pg.write(text, interval=max(0.0, float(interval)))
    return f"Typed: {text[:60]}"


def keyboard_press(key: str) -> str:
    """Presses a single key, e.g. 'enter', 'esc', 'tab', 'backspace',
    'f5'. Full key list: pyautogui.KEYBOARD_KEYS"""
    pg = _pyautogui()
    key = (key or "").strip().lower()
    if not key:
        raise ValueError("No key given")
    pg.press(key)
    return f"Pressed key: {key}"


def keyboard_hotkey(keys: list) -> str:
    """Presses a key combo together, e.g. ['ctrl', 'c'] or ['alt', 'tab']."""
    pg = _pyautogui()
    if not keys or not isinstance(keys, list):
        raise ValueError("keys must be a non-empty list, e.g. ['ctrl', 'c']")
    keys = [str(k).strip().lower() for k in keys if str(k).strip()]
    if not keys:
        raise ValueError("keys must be a non-empty list, e.g. ['ctrl', 'c']")
    pg.hotkey(*keys)
    return f"Pressed hotkey: {'+'.join(keys)}"


def mouse_position() -> dict:
    pg = _pyautogui()
    x, y = pg.position()
    return {"x": x, "y": y}


# ---------------------------------------------------------------------------
# Screen & camera "understanding" — takes a screenshot/photo, then asks
# Gemini's vision to actually describe/answer about what's in it. This is
# different from take_screenshot/webcam_photo above, which just SAVE the
# image — these ANALYZE it and return text.
# ---------------------------------------------------------------------------

def see_screen(question: str, save_dir: str) -> str:
    """Takes a fresh screenshot right now and asks Gemini about it."""
    from backend import gemini

    path = take_screenshot(save_dir)
    with open(path, "rb") as f:
        image_bytes = f.read()

    prompt = question.strip() if question else "Describe what's currently on this screen."
    return gemini.ask_gemini(prompt, image_bytes=image_bytes, image_mime_type="image/png")


def see_camera(question: str, save_dir: str) -> str:
    """Takes a fresh webcam photo right now and asks Gemini about it."""
    from backend import gemini

    path = webcam_photo(save_dir)
    with open(path, "rb") as f:
        image_bytes = f.read()

    prompt = question.strip() if question else "Describe what you see through this camera."
    return gemini.ask_gemini(prompt, image_bytes=image_bytes, image_mime_type="image/png")
