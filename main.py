"""
Arika - main entry point.

Usage:
    python main.py            # start the web app (http://localhost:5000)
    python main.py --cli      # start the old terminal chat instead
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def run_web():
    from backend.app import create_app
    app = create_app()
    # host='0.0.0.0' lets other devices on the same Wi-Fi connect.
    # ssl_context='adhoc' gives a temporary HTTPS cert (needed for the
    # browser mic permission on phones).
    import webbrowser
    import threading

    url = "https://localhost:5000/"

    def _open_browser():
        try:
            webbrowser.open(url)
        except Exception:
            print(f"Please open your browser and visit: {url}")

    def _auto_connect_phone():
        try:
            from backend import phone_automation
            print(f"[Phone] {phone_automation.auto_connect()}")
        except Exception as e:
            # Never let a phone-connection hiccup stop the app from starting.
            print(f"[Phone] Auto-connect skipped due to error: {e}")

    # Start a timer to open the browser shortly after the server starts.
    threading.Timer(1.5, _open_browser).start()
    # Try reconnecting the phone over adb in the background — doesn't
    # block server startup, and never crashes it if the phone is offline.
    threading.Thread(target=_auto_connect_phone, daemon=True).start()

    # Disable the reloader here to avoid the browser being opened twice.
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False, ssl_context="adhoc")


def run_cli():
    from backend.cli import main as cli_main
    cli_main()


if __name__ == "__main__":
    if "--cli" in sys.argv:
        run_cli()
    else:
        run_web()
