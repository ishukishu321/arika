import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_minecraft_port_defaults_match():
    python_file = (ROOT / "backend" / "minecraft_manager.py").read_text(encoding="utf-8")
    js_file = (ROOT / "minecraft_bot" / "bot.js").read_text(encoding="utf-8")

    assert 'DEFAULT_BOT_PORT = 39399' in python_file
    assert 'ARIKA_MC_BOT_PORT || process.env.PORT || DEFAULT_PORT' in js_file
