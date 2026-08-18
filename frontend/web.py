"""
Moved! The Flask app factory now lives at backend/app.py (speech/TTS logic
was pulled out into backend/speech/). Run the project from the project root:

    python main.py
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True, ssl_context="adhoc")
