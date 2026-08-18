"""
Example plugin. Copy this file's shape to make your own — drop the new
.py file in this same folder and Arika will auto-detect it, no other
setup needed.
"""

PLUGIN_NAME = "example_echo"
PLUGIN_DESC = "Echoes back whatever text you send it (template for new plugins)."


def run(data: dict) -> str:
    text = (data or {}).get("text", "")
    if not text:
        return "example_echo: send {'text': '...'} in data to see it echoed back."
    return f"Echo: {text}"
