"""
Plugin system
=============
"Drop a Python file, new skill unlocked."

Put a .py file in the top-level `plugins/` folder (created automatically
next to main.py). Each plugin file must define:

    PLUGIN_NAME = "my_plugin"          # required, unique, snake_case
    PLUGIN_DESC = "One line about what this does"   # required
    def run(data: dict) -> str:        # required
        ...
        return "some result string"

That's it. No registration, no editing command_router.py — Arika discovers
it automatically. Example plugin lives at plugins/example_echo.py.

Safety note: a plugin is arbitrary Python code that runs with the same
permissions as the rest of the app. Only Admin can trigger run_plugin (same
gate as every other automation action in command_router.py), but you're
still trusting whatever .py file ends up in that folder — don't drop in
scripts you didn't write/review, same as automation_scripts/.
"""

import importlib.util
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGINS_DIR = os.path.join(PROJECT_ROOT, "plugins")

_cache = {}  # plugin_name -> module


def _plugins_dir_ready():
    os.makedirs(PLUGINS_DIR, exist_ok=True)
    return PLUGINS_DIR


def discover_plugins(force_reload: bool = False) -> dict:
    """Scan plugins/ and (re)load every valid plugin file. Returns
    {plugin_name: {"desc": ..., "file": ...}}. Bad plugins (missing
    required attributes, import errors) are skipped and logged, never
    crash discovery for the others."""
    global _cache
    if force_reload:
        _cache = {}

    folder = _plugins_dir_ready()
    found = {}

    for fname in os.listdir(folder):
        if not fname.endswith(".py") or fname.startswith("_"):
            continue
        fpath = os.path.join(folder, fname)
        mod_key = f"arika_plugin_{fname[:-3]}"

        try:
            spec = importlib.util.spec_from_file_location(mod_key, fpath)
            module = importlib.util.module_from_spec(spec)
            sys.modules[mod_key] = module
            spec.loader.exec_module(module)

            name = getattr(module, "PLUGIN_NAME", None)
            desc = getattr(module, "PLUGIN_DESC", "")
            run_fn = getattr(module, "run", None)

            if not name or not callable(run_fn):
                print(f"[Plugin] Skipped '{fname}': needs PLUGIN_NAME and a run(data) function.")
                continue

            _cache[name] = module
            found[name] = {"desc": desc, "file": fname}
        except Exception as e:
            print(f"[Plugin] Failed to load '{fname}': {e}")

    return found


def list_plugins() -> list:
    found = discover_plugins()
    return [{"name": n, "desc": v["desc"], "file": v["file"]} for n, v in found.items()]


def run_plugin(name: str, params: dict = None) -> str:
    name = (name or "").strip()
    if not name:
        raise ValueError("No plugin name given.")

    discover_plugins()  # always refresh so newly-dropped files are picked up
    module = _cache.get(name)
    if module is None:
        available = ", ".join(_cache.keys()) or "(none installed)"
        raise ValueError(f"No plugin named '{name}' found. Available: {available}")

    result = module.run(params or {})
    return str(result) if result is not None else f"Plugin '{name}' ran (no output)"
