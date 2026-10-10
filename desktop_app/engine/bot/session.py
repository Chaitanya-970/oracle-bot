"""Cooperative session checks, always executed on Playwright's owner thread."""
import re
import time
from playwright.sync_api import Error as PlaywrightError
from bot.apex_helpers import surfaces, page_text, safe_click
from bot.diagnostics import log_info


class SessionExpired(RuntimeError):
    pass


def transient_browser_error(exc):
    return isinstance(exc, PlaywrightError) and bool(re.search(
        r'frame was detached|execution context was destroyed|cannot find context|navigation|not attached', str(exc), re.I))


def maintain_session(page):
    for frame in surfaces(page):
        try:
            if frame.is_detached():
                continue
            dialogs = frame.locator(".ui-dialog:visible, [role='dialog']:visible, .t-Dialog:visible, .a-SessionTimeout:visible")
            # Snapshot actual nodes: indexed locators can rebind or wait for a
            # disappeared modal during assessment navigation.
            for dialog in dialogs.element_handles():
                if not dialog.is_visible():
                    continue
                text = dialog.inner_text()
                if not re.search(r"session|inactivity|inactive|logged out", text, re.I):
                    continue
                if re.search(r"session (?:has )?expired|session (?:has )?ended|logged out", text, re.I):
                    raise SessionExpired("Oracle session expired. Sign in again in the browser.")
                controls = dialog.query_selector_all("button, a, input[type='button'], input[type='submit']")
                for el in controls:
                    label = (el.get_attribute("value") or el.inner_text()).strip()
                    if re.fullmatch(r"(?:Extend(?: Session)?|Stay (?:Signed|Logged) In|Continue(?: Session)?|Keep (?:Session )?Alive|Yes|OK)", label, re.I):
                        if safe_click(el):
                            log_info("Extended Oracle session from the timeout warning.")
                            return True
                        if not dialog.is_visible():
                            return False
                        raise RuntimeError("Session extension button could not be clicked.")
                if not dialog.is_visible():
                    continue
                raise RuntimeError("Session warning appeared, but its extension button was not recognized.")
        except SessionExpired:
            raise
        except PlaywrightError as exc:
            if not transient_browser_error(exc):
                raise
    text = page_text(page)
    if re.search(r"signon\.oracle\.com/(?:signin|login)|login\.oracle\.com", page.url, re.I):
        raise SessionExpired("Oracle returned to its sign-in service.")
    if re.search(r"(?:your )?session (?:has )?(?:expired|ended)", text, re.I):
        raise SessionExpired("Oracle session expired. Sign in again in the browser.")
    for frame in surfaces(page):
        try:
            if not frame.is_detached() and frame.locator('input[type="password"]:visible').count():
                raise SessionExpired("Oracle returned to the login page.")
        except SessionExpired:
            raise
        except PlaywrightError as exc:
            if not transient_browser_error(exc):
                raise
    return False


def session_wait(page, seconds):
    deadline = time.monotonic() + seconds
    while True:
        maintain_session(page)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        page.wait_for_timeout(min(500, remaining * 1000))


def wait_until(page, predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        maintain_session(page)
        try:
            if predicate():
                return True
        except PlaywrightError as exc:
            if not transient_browser_error(exc):
                raise
        page.wait_for_timeout(250)
    return False


def native_dialog(dialog):
    # Native session confirmation only; unknown alerts are surfaced by page state.
    if dialog.type == "confirm" and re.search(r"session", dialog.message, re.I) and re.search(r"extend|continue|remain|stay", dialog.message, re.I):
        dialog.accept()
        log_info("Extended Oracle session from the browser confirmation.")
    elif dialog.type == "confirm" and re.search(r"assessment", dialog.message, re.I) and re.search(r"submit|complete|finish", dialog.message, re.I):
        dialog.accept()
    else:
        dialog.dismiss()
