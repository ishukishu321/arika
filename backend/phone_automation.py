"""
Phone automation (via ADB)
==========================
Controls an Android phone from THIS PC using ADB (Android Debug Bridge).
This runs on the same Flask server as the PC automation — so it doesn't
matter whether the Admin talks to Arika from the PC's browser or from
their phone's browser (over the same LAN, https://<pc-ip>:5000): the
COMMAND still executes here, on the PC, which then tells the connected
phone what to do.

-------------------------------------------------------------------------
ONE-TIME SETUP (needed once per phone):
-------------------------------------------------------------------------
1. On the phone: Settings -> About phone -> tap "Build number" 7 times
   to unlock Developer Options.
2. Settings -> System -> Developer Options -> turn on:
     - "Wireless debugging" (Android 11+, no cable needed after pairing)
     - or "USB debugging" (works on any version, needs a USB cable once)
3. On this PC: install Android "platform-tools" (gives you the `adb`
   command) and add its folder to your PATH:
     https://developer.android.com/tools/releases/platform-tools
4. Pair once:
     Wireless — Developer Options -> Wireless debugging -> "Pair device
     with pairing code", then on the PC run:
         adb pair <ip>:<port>      (enter the 6-digit code shown)
         adb connect <ip>:<port>
     USB — just plug the cable in and tap "Allow" on the phone's popup.
5. Check it worked:  adb devices
     Should show your phone's ID with status "device" (not
     "unauthorized" or empty). After this, phone stays remembered — no
     need to re-pair every time (wireless debugging does need the phone
     and PC on the same Wi-Fi each session, though).
-------------------------------------------------------------------------

Known limitation: phone_call() tries to auto-dial (ACTION_CALL), but
actually placing a call needs the CALL_PHONE permission, which not every
device/ROM grants to adb's shell user by default. When that happens this
falls back to ACTION_DIAL (opens the dialer with the number ready — one
tap to confirm) instead of silently failing.
"""

import os
import subprocess
from datetime import datetime

# Friendly name -> Android package name. Extend as you install more apps.
PHONE_APP_PACKAGES = {
    "whatsapp": "com.whatsapp",
    "youtube": "com.google.android.youtube",
    "chrome": "com.android.chrome",
    "instagram": "com.instagram.android",
    "spotify": "com.spotify.music",
    "gmail": "com.google.android.gm",
    "camera": "com.android.camera",
    "settings": "com.android.settings",
}


def _adb(*args, timeout=15) -> str:
    try:
        result = subprocess.run(
            ["adb"] + list(args),
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "adb not found on this PC. Install Android platform-tools and "
            "add it to PATH: "
            "https://developer.android.com/tools/releases/platform-tools"
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("adb command timed out — is the phone connected?")

    output = (result.stdout or "") + (result.stderr or "")
    return output.strip()


def phone_status() -> dict:
    output = _adb("devices", "-l")
    lines = [
        line for line in output.splitlines()
        if line.strip() and "List of devices" not in line
    ]
    # With `-l`, a connected line looks like:
    #   "<serial>          device product:... model:... transport_id:..."
    # (space-separated, extra columns after "device") — NOT the plain
    # tab-separated "<serial>\tdevice" you get without -l. Checking
    # endswith("device") or "\tdevice" breaks the moment -l adds those
    # extra columns, so split on whitespace and check the 2nd field.
    connected = any(
        line.split()[1] == "device"
        for line in lines
        if len(line.split()) >= 2
    )
    return {"connected": connected, "raw_lines": lines}


def _ensure_connected():
    status = phone_status()
    if not status["connected"]:
        raise RuntimeError(
            "No phone connected over adb right now. Run 'adb devices' to "
            "check — if it's empty or says 'unauthorized', re-pair (see "
            "the setup notes at the top of phone_automation.py)."
        )


def auto_connect() -> str:
    """Best-effort reconnect for wireless debugging, meant to run once at
    app startup (see main.py). USB-connected phones don't need this — they
    show up in `adb devices` the moment the cable is plugged in.

    For wireless debugging, the *pairing* (adb pair) only has to happen
    once ever, but the *connection* (adb connect) itself drops whenever
    the adb server restarts or the phone's IP changes on the LAN — so it
    normally needs to be re-run by hand every session. This reads the
    address saved from Settings (phone_adb_address, e.g.
    "192.168.1.42:5555") and tries `adb connect` on it automatically, so
    you don't have to do it manually every time.

    Never raises — startup shouldn't crash because the phone happens to be
    off or off the Wi-Fi that day. Returns a short human-readable status
    string instead, meant for a startup log line.
    """
    from backend import settings_manager  # local import: avoids import cycle

    if phone_status()["connected"]:
        return "Phone already connected over adb."

    address = (settings_manager.get_phone_adb_address() or "").strip()
    if not address:
        return (
            "No saved phone adb address (Settings > phone_adb_address) — "
            "skipping auto-connect. Plug in USB, or save an address like "
            "192.168.1.42:5555 to auto-connect over Wi-Fi next time."
        )

    try:
        output = _adb("connect", address, timeout=10)
    except RuntimeError as e:
        return f"Phone auto-connect failed: {e}"

    if "connected to" in output.lower():
        return f"Phone auto-connected: {output}"
    return (
        f"Phone auto-connect attempt to {address} did not succeed "
        f"(adb said: {output!r}). Phone may be off, off Wi-Fi, or its IP "
        f"changed — update phone_adb_address in Settings if the IP moved."
    )


def phone_open_app(name: str) -> str:
    _ensure_connected()
    name_key = (name or "").strip().lower()
    package = PHONE_APP_PACKAGES.get(name_key)
    if not package:
        raise ValueError(
            f"Don't know the package name for '{name}' yet. Add it to "
            f"PHONE_APP_PACKAGES in phone_automation.py (find it via "
            f"'adb shell pm list packages | grep {name_key}')."
        )
    _adb("shell", "monkey", "-p", package, "-c",
         "android.intent.category.LAUNCHER", "1")
    return f"Opened '{name}' on phone"


def phone_open_website(url: str) -> str:
    _ensure_connected()
    url = (url or "").strip()
    if not url:
        raise ValueError("No URL given")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    _adb("shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", url)
    return f"Opened website on phone: {url}"


def phone_call(phone: str) -> str:
    _ensure_connected()
    phone = (phone or "").strip()
    if not phone:
        raise ValueError("No phone number given")

    output = _adb("shell", "am", "start", "-a",
                   "android.intent.action.CALL", "-d", f"tel:{phone}")

    if "permission denial" in output.lower() or "securityexception" in output.lower():
        _adb("shell", "am", "start", "-a", "android.intent.action.DIAL",
             "-d", f"tel:{phone}")
        return (
            f"Couldn't auto-dial (permission not granted on this phone) — "
            f"opened the dialer with {phone} ready, tap call to confirm."
        )

    return f"Calling {phone} on phone"


def phone_lock() -> str:
    _ensure_connected()
    _adb("shell", "input", "keyevent", "26")  # power button toggle
    return "Phone screen locked/toggled"


def phone_volume(direction: str) -> str:
    _ensure_connected()
    direction = (direction or "").strip().lower()
    keycodes = {"up": "24", "down": "25"}
    if direction not in keycodes:
        raise ValueError("direction must be 'up' or 'down'")
    _adb("shell", "input", "keyevent", keycodes[direction])
    return f"Phone volume: {direction}"


def phone_screenshot(save_dir: str) -> str:
    _ensure_connected()
    os.makedirs(save_dir, exist_ok=True)
    filename = f"phone_screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    path = os.path.join(save_dir, filename)

    try:
        result = subprocess.run(
            ["adb", "exec-out", "screencap", "-p"],
            capture_output=True, timeout=15,
        )
    except FileNotFoundError:
        raise RuntimeError("adb not found. Install Android platform-tools.")

    if not result.stdout:
        raise RuntimeError("Screenshot failed — no data returned by adb.")

    with open(path, "wb") as f:
        f.write(result.stdout)
    return path


def phone_battery_status() -> dict:
    """Battery level/status via `adb shell dumpsys battery` — no special
    permission needed, works on every device."""
    _ensure_connected()
    output = _adb("shell", "dumpsys", "battery")
    info = {}
    for line in output.splitlines():
        line = line.strip()
        if ":" in line:
            key, _, value = line.partition(":")
            info[key.strip()] = value.strip()
    level = info.get("level")
    charging = info.get("AC powered") == "true" or info.get("USB powered") == "true"
    return {
        "level_percent": int(level) if level and level.isdigit() else None,
        "charging": charging,
        "raw": info,
    }


def phone_wifi(state: str) -> str:
    """Toggle Wi-Fi. state: 'on' or 'off'. Uses `svc wifi`, which needs no
    extra permission over adb's shell user."""
    _ensure_connected()
    state = (state or "").strip().lower()
    if state not in ("on", "off"):
        raise ValueError("state must be 'on' or 'off'")
    _adb("shell", "svc", "wifi", "enable" if state == "on" else "disable")
    return f"Phone Wi-Fi turned {state}"


def phone_bluetooth(state: str) -> str:
    """Toggle Bluetooth. state: 'on' or 'off'."""
    _ensure_connected()
    state = (state or "").strip().lower()
    if state not in ("on", "off"):
        raise ValueError("state must be 'on' or 'off'")
    _adb("shell", "svc", "bluetooth", "enable" if state == "on" else "disable")
    return f"Phone Bluetooth turned {state}"


def phone_send_sms(phone: str, message: str) -> str:
    """Opens the SMS app with the number and message pre-filled. Same
    honesty pattern as phone_call: adb can't tap 'Send' without the
    READ/SEND_SMS permission (not granted to the shell user on most
    devices), so this gets it 99% of the way and leaves one tap to
    actually send — safer than silently trying to auto-send anyway."""
    _ensure_connected()
    phone = (phone or "").strip()
    message = (message or "").strip()
    if not phone:
        raise ValueError("No phone number given")
    if not message:
        raise ValueError("No message given")

    _adb(
        "shell", "am", "start", "-a", "android.intent.action.SENDTO",
        "-d", f"sms:{phone}", "--es", "sms_body", message,
    )
    return (
        f"Opened SMS to {phone} with the message ready — tap send on the "
        f"phone to confirm."
    )


def phone_camera_photo(save_dir: str) -> str:
    """Opens the camera app, fires the shutter via the hardware camera
    keycode, then pulls the newest file out of DCIM/Camera onto this PC.

    Known limitation: some camera apps/ROMs ignore KEYCODE_CAMERA, and the
    "newest file" pull is a best guess (there's no reliable event telling
    adb exactly which file the shutter press produced) — if the pulled
    file looks wrong or old, the shutter likely didn't fire on that phone.
    """
    _ensure_connected()
    os.makedirs(save_dir, exist_ok=True)

    _adb("shell", "am", "start", "-a", "android.media.action.IMAGE_CAPTURE")
    import time
    time.sleep(2)  # give the camera app time to open
    _adb("shell", "input", "keyevent", "27")  # KEYCODE_CAMERA
    time.sleep(2)  # give it time to save the file

    listing = _adb("shell", "ls", "-t", "/sdcard/DCIM/Camera")
    files = [f.strip() for f in listing.splitlines() if f.strip()]
    if not files:
        raise RuntimeError(
            "No photo found in DCIM/Camera after triggering the shutter — "
            "this phone's camera app may not respond to KEYCODE_CAMERA. "
            "Take the photo manually and use phone_screenshot as a fallback."
        )
    newest = files[0]
    remote_path = f"/sdcard/DCIM/Camera/{newest}"
    local_path = os.path.join(save_dir, newest)

    _adb("pull", remote_path, local_path, timeout=20)
    if not os.path.exists(local_path):
        raise RuntimeError(f"Failed to pull {remote_path} from the phone.")
    return local_path


def phone_screen_mirror() -> str:
    """Launches scrcpy (a free, separate tool — NOT part of this project)
    to mirror + control the phone screen live in a window on this PC.

    One-time setup: download scrcpy and put it on PATH:
        https://github.com/Genymobile/scrcpy
    It reuses the same adb connection/pairing already set up for phone
    automation — no extra phone-side setup needed.

    This starts scrcpy as a separate detached window and returns
    immediately; it does not block the Flask server."""
    _ensure_connected()
    try:
        subprocess.Popen(
            ["scrcpy"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "scrcpy not found on this PC. It's a separate free tool for "
            "screen mirroring — download it and add it to PATH: "
            "https://github.com/Genymobile/scrcpy"
        )
    return "Opening phone screen mirror window (scrcpy)..."
