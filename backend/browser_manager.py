"""
Browser control
===============
Real, in-page browser automation (not just webbrowser.open like
automation.open_website). Uses Selenium + Chrome so Arika can actually
navigate, click buttons/links by their visible text, type into fields,
scroll, and read page content back.

Needs: pip install selenium webdriver-manager
(webdriver-manager auto-downloads the matching chromedriver — no manual
driver setup needed, as long as Chrome itself is installed on the PC.)

Keeps ONE browser window open across commands (module-level singleton) so
"open youtube -> click search -> type something" works as a sequence
instead of opening a fresh tab every time. Call browser_close() to end
the session.

TWO CONNECTION MODES
---------------------
1. LAUNCH MODE (default, zero setup): Selenium starts its own Chrome using
   a dedicated profile (~/.arika_browser_profile). Works for most sites,
   but Google specifically detects and blocks "Sign in with Google" in an
   automation-launched browser ("This browser or app may not be secure").

2. ATTACH MODE (fixes Google sign-in): Selenium instead connects to a
   Chrome window YOU started normally — since a human launched it, Google
   doesn't flag it. One-time setup:
     a) Fully close every Chrome window first.
     b) Launch Chrome with a debug port, e.g. (Windows, adjust the path if
        Chrome is installed elsewhere):
        "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\\ArikaChromeProfile"
        (mac/Linux: run the `google-chrome`/`chrome` binary with the same
        two flags instead.)
     c) Log into whatever you need (Google, ChatGPT, etc.) normally in
        that window — it's just regular Chrome.
     d) In Arika's Settings panel, save `browser_debug_port: 9222` (must
        match the port used in step b).
   From then on, every browser_* command controls THAT window instead of
   launching a new automated one. Leave it open while using browser
   commands; close it and remove the setting to go back to LAUNCH MODE.
"""

import os

_driver = None

# A DEDICATED Chrome profile just for Arika's automated browser — separate
# from your everyday Chrome profile so it never conflicts with a Chrome
# window you already have open. First time this runs, it starts blank —
# log into whatever sites you need ONCE, and those cookies/sessions get
# saved here permanently for every future run (no re-login needed after).
PROFILE_DIR = os.path.join(os.path.expanduser("~"), ".arika_browser_profile")


def _get_driver():
    global _driver
    if _driver is not None:
        try:
            _ = _driver.title  # cheap liveness check
            return _driver
        except Exception:
            _driver = None  # window was closed manually, start a fresh one

    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager
    except ImportError:
        raise RuntimeError(
            "selenium/webdriver-manager not installed. Run: "
            "pip install selenium webdriver-manager"
        )

    from backend import settings_manager
    debug_port = (settings_manager.load_settings() or {}).get("browser_debug_port")

    options = webdriver.ChromeOptions()

    if debug_port:
        # ATTACH MODE — connects to a Chrome window YOU already launched
        # normally (see instructions below). This Chrome is a real,
        # human-started browser, not one Selenium spawned itself, so
        # Google/other sites don't flag it as automation. This is the
        # reliable way to use anything that requires "Sign in with
        # Google" (Gmail, YouTube login, etc.) inside browser control.
        options.debugger_address = f"127.0.0.1:{debug_port}"
        _driver = webdriver.Chrome(options=options)
        return _driver

    # LAUNCH MODE (default, no setup needed) — Selenium starts its own
    # Chrome using a dedicated profile. Fine for anything that doesn't
    # need "Sign in with Google" specifically. A few anti-detection flags
    # are added, but Google's automation detection is aggressive and may
    # still block sign-in here — if that happens, switch to ATTACH MODE
    # (see PATCH_NOTES.md / browser_manager.py docstring for setup steps).
    options.add_argument("--start-maximized")
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument(f"--user-data-dir={PROFILE_DIR}")

    service = Service(ChromeDriverManager().install())
    _driver = webdriver.Chrome(service=service, options=options)
    return _driver


def browser_open(url: str) -> str:
    url = (url or "").strip()
    if not url:
        raise ValueError("No URL given")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    driver = _get_driver()
    driver.get(url)
    return f"Browser opened: {url}"


def _find_clickable_by_text(driver, text: str):
    from selenium.webdriver.common.by import By

    text_lower = text.strip().lower()
    # Try links, buttons, and generic clickable elements containing the text.
    xpath = (
        f"//*[self::a or self::button or @role='button']"
        f"[contains(translate(normalize-space(.), "
        f"'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), "
        f"'{text_lower}')]"
    )
    elements = driver.find_elements(By.XPATH, xpath)
    if not elements:
        raise ValueError(f"No clickable element found matching text: '{text}'")
    return elements[0]


def browser_click(text: str = None, selector: str = None) -> str:
    """Click something on the current page. Give EITHER visible text
    (e.g. 'Sign in') OR a CSS selector (e.g. '#submit-btn') — text is
    easier when you don't know the page's internals."""
    driver = _get_driver()

    if selector:
        from selenium.webdriver.common.by import By
        elements = driver.find_elements(By.CSS_SELECTOR, selector)
        if not elements:
            raise ValueError(f"No element found for selector: '{selector}'")
        elements[0].click()
        return f"Clicked selector: {selector}"

    if text:
        el = _find_clickable_by_text(driver, text)
        el.click()
        return f"Clicked: {text}"

    raise ValueError("Give either 'text' or 'selector' to click.")


def browser_type(text: str, selector: str = None, submit: bool = False) -> str:
    """Type into an input field. If selector is omitted, types into
    whichever field is currently focused/active on the page."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys

    driver = _get_driver()

    if selector:
        elements = driver.find_elements(By.CSS_SELECTOR, selector)
        if not elements:
            raise ValueError(f"No input found for selector: '{selector}'")
        target = elements[0]
    else:
        target = driver.switch_to.active_element

    target.send_keys(text or "")
    if submit:
        target.send_keys(Keys.RETURN)

    return f"Typed into page: {text[:60]}"


def browser_scroll(direction: str = "down", amount: int = 600) -> str:
    driver = _get_driver()
    direction = (direction or "down").strip().lower()
    delta = amount if direction == "down" else -amount
    driver.execute_script(f"window.scrollBy(0, {delta});")
    return f"Scrolled {direction} by {amount}px"

def browser_get_text(selector: str = None, max_chars: int = 2000) -> str:
    """Reads visible text back off the page — either the whole body, or a
    specific element if a CSS selector is given. Useful for 'what does
    this page say' type asks."""
    from selenium.webdriver.common.by import By

    driver = _get_driver()
    if selector:
        elements = driver.find_elements(By.CSS_SELECTOR, selector)
        if not elements:
            raise ValueError(f"No element found for selector: '{selector}'")
        text = elements[0].text
    else:
        text = driver.find_element(By.TAG_NAME, "body").text

    text = text.strip()
    return text[:max_chars] if text else "(no visible text found)"


def browser_close() -> str:
    global _driver
    if _driver is None:
        return "No browser session was open."
    try:
        _driver.quit()
    finally:
        _driver = None
    return "Browser session closed."
