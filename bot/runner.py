"""Bounded course traversal with verified transitions and explicit failures."""
import re
from playwright.sync_api import sync_playwright
from bot.config import BROWSER_PROFILE_DIR, BROWSER_CHANNEL, HEADLESS, STEP_DELAY, PAGE_LOAD_TIMEOUT, ORACLE_HOME_URL
from bot.diagnostics import log_info, log_success, log_warn, log_error, capture_diagnostic
from bot.apex_helpers import (safe_click, click_button_by_text, matching_button,
    is_assessment_question_page, is_quiz_landing_page, is_quiz_start_modal,
    extract_question_and_options, visible_locators, page_text, question_identity,
    wizard_steps, step_complete, is_multiple_choice_question)
from bot.groq_solver import solve_with_session
from bot.session import maintain_session, session_wait, wait_until, native_dialog, SessionExpired

RETURN_COURSE = [r"^Return to Course Lessons$", r"^Return to Course$", r"^Course Outline$", r"^Exit$", r"^Course$"]
RESULTS = r"Results Summary|Assessment Score|Assessment (?:is )?Complete|Score Summary|Percentage Scored|Mastery Score"


def fail(page, reason):
    capture_diagnostic(page, reason)
    log_error(reason)
    return False


def fingerprint(page):
    frames = []
    for frame in page.frames:
        try:
            steps = frame.locator('li.t-WizardSteps-step')
            status = tuple((item.get_attribute('class'), step_complete(item)) for item in steps.all())
            frames.append((frame.url, frame.locator('body').inner_text(timeout=2000), status))
        except Exception:
            continue
    return page.url, tuple(frames)


def finish_assessment(page):
    maintain_session(page)
    if not re.search(RESULTS, page_text(page), re.I):
        if click_button_by_text(page, [r"^Complete Assessment$", r"^Submit Assessment$"]):
            session_wait(page, 0.5)
            click_button_by_text(page, [r"^Complete Assessment$", r"^Submit Assessment$", r"^Yes$", r"^Confirm$"], modal_only=True)
            wait_until(page, lambda: bool(re.search(RESULTS, page_text(page), re.I)))

    # On Score Summary (Page 192), click View Results if present to reveal Return to Course Lessons
    if click_button_by_text(page, [r"^View Results$"]):
        session_wait(page, 1.0)

    if not click_button_by_text(page, RETURN_COURSE):
        return fail(page, "Results reached, but Return to Course was not found.")
    if not wait_until(page, lambda: not re.search(RESULTS, page_text(page), re.I) or bool(wizard_steps(page) or section_controls(page))):
        return fail(page, "Return to Course did not leave the assessment results.")
    log_success("Assessment submitted; results confirmed and returned to course.")
    return True


def solve_current_quiz(page):
    seen = set()
    for _ in range(200):
        maintain_session(page)
        identity = question_identity(page)
        if identity is None:
            return finish_assessment(page)
        if identity in seen:
            return fail(page, "Question did not advance; refusing to submit the same answer again.")
        text, image, options, locators = extract_question_and_options(page)
        if not text or len(options) < 2:
            return fail(page, "Could not extract the question and its answer choices.")
        multiple = is_multiple_choice_question(page, text, locators)
        log_info(f"Solving {identity[1]} ({len(options)} options, multiple={multiple}).")
        try:
            indices = solve_with_session(page, text, options, image, multiple)
        except SessionExpired:
            raise
        except Exception as exc:
            return fail(page, f"Groq solver failed: {exc}")
        maintain_session(page)
        if question_identity(page) != identity:
            return fail(page, "Question changed while the AI was answering; no answer was submitted.")
        # Reacquire choices: extending the session may rerender the document.
        _, _, fresh_options, locators = extract_question_and_options(page)
        if options != fresh_options:
            return fail(page, "Answer choices changed while solving.")
        if not indices or any(type(i) is not int or i < 0 or i >= len(locators) for i in indices):
            return fail(page, "Invalid answer indices; nothing submitted.")
        if len(indices) > 1:
            multiple = True
        if not multiple and len(indices) != 1:
            return fail(page, "Multiple answers returned for a radio question.")
        for i, loc in enumerate(locators):
            checked = loc.get_attribute("aria-checked") == "true"
            if (i in indices and not checked) or (multiple and i not in indices and checked):
                if not safe_click(loc):
                    return fail(page, f"Could not select/deselect answer {i}.")
        for i, loc in enumerate(locators):
            state = loc.get_attribute("aria-checked")
            if state is not None and (state == "true") != (i in indices):
                return fail(page, f"Answer {i} did not reach the requested selection state.")
        seen.add(identity)
        if not click_button_by_text(page, [r"^Submit Answer$", r"^Next Question$", r"^Next$"]):
            return finish_assessment(page)
        if not wait_until(page, lambda: question_identity(page) != identity or matching_button(page, [r"^Next Question$", r"^Next$"]) is not None):
            return fail(page, "Submit Answer produced no next question or feedback navigation.")
        if question_identity(page) == identity:
            if not click_button_by_text(page, [r"^Next Question$", r"^Next$"]) or not wait_until(page, lambda: question_identity(page) != identity):
                return fail(page, "Feedback screen did not advance to the next question.")
    return fail(page, "Assessment exceeded the 200-question safety limit.")


def handle_quiz_landing_and_start(page):
    maintain_session(page)
    if not is_quiz_start_modal(page):
        if not click_button_by_text(page, [r"^Take an Assessment$"]):
            return fail(page, "Could not open assessment.")
        if not wait_until(page, lambda: is_quiz_start_modal(page) or is_assessment_question_page(page)):
            return fail(page, "Assessment did not show a Start dialog or question.")
    if is_quiz_start_modal(page):
        if not click_button_by_text(page, [r"^Start$"], modal_only=True):
            return fail(page, "Could not click Start in the assessment dialog.")
        if not wait_until(page, lambda: is_assessment_question_page(page)):
            return fail(page, "Start did not reach an assessment question.")
    return solve_current_quiz(page)


def process_course_lessons(page):
    for _ in range(150):
        session_wait(page, STEP_DELAY)
        steps = wizard_steps(page)
        if steps and all(step_complete(item) for _, item in steps):
            log_success(f"Confirmed all {len(steps)} sidebar steps are complete.")
            return True
        if is_quiz_start_modal(page) or is_quiz_landing_page(page):
            if not handle_quiz_landing_and_start(page):
                return False
            continue
        if is_assessment_question_page(page):
            if not solve_current_quiz(page):
                return False
            continue
        if re.search(RESULTS, page_text(page), re.I):
            if not finish_assessment(page):
                return False
            continue
        before = fingerprint(page)
        incomplete = [item for _, item in steps if not step_complete(item)]
        if incomplete:
            active_steps = [item for _, item in steps if "is-active" in (item.get_attribute("class") or "").split()]
            # If the currently opened step is already complete, jump directly to the first incomplete item!
            if active_steps and step_complete(active_steps[0]) and active_steps[0] != incomplete[0]:
                target = incomplete[0]
                link = target.locator("a.t-WizardSteps-wrap, a, .t-WizardSteps-label").first
                log_info(f"Current step is already complete. Jumping directly to incomplete step ({len(incomplete)} left)...")
                if safe_click(link) and wait_until(page, lambda: fingerprint(page) != before):
                    continue

        if click_button_by_text(page, [r"^Save and Continue$", r"^Save Progress$"]):
            if not wait_until(page, lambda: fingerprint(page) != before):
                return fail(page, "Save action did not change the lesson or completion status.")
            log_info("Save action changed the course page; checking completion.")
            continue
        if incomplete:
            link = incomplete[0].locator("a.t-WizardSteps-wrap, a").first
            if not safe_click(link) or not wait_until(page, lambda: fingerprint(page) != before):
                return fail(page, "Incomplete sidebar lesson could not be opened or made no progress.")
            continue
        # An outline reached after saving is evidence of navigation, not 100% completion.
        if list(visible_locators(page, "li.t-MediaList-item a.t-MediaList-itemWrap")):
            return True
        return fail(page, "Unrecognized course state; completion cannot be confirmed.")
    return fail(page, "Section exceeded 150 actions; completion was not confirmed.")


def course_controls(page):
    controls = []
    for frame, item in visible_locators(page, "button, a"):
        if re.fullmatch(r"Take Class", item.inner_text().strip(), re.I):
            controls.append((frame, item))
    return controls


def section_controls(page):
    return [(frame, item) for frame, item in visible_locators(page, "li.t-MediaList-item a.t-MediaList-itemWrap")
            if (item.get_attribute("href") or "").strip() not in ("", "#")]


def item_label(item):
    try:
        title = item.locator('.t-MediaList-title')
        return title.first.inner_text().strip() if title.count() else item.inner_text().strip()
    except Exception:
        return ""


def frame_path(frame):
    indices = []
    while frame.parent_frame is not None:
        parent = frame.parent_frame
        indices.append([child for child in parent.child_frames if not child.is_detached()].index(frame))
        frame = parent
    return list(reversed(indices))


def resolve_frame(page, indices):
    frame = page.main_frame
    for index in indices:
        children = [child for child in frame.child_frames if not child.is_detached()]
        if index >= len(children):
            return None
        frame = children[index]
    return frame


def walk_courses(page, depth=0):
    """Revisit each parent list and reacquire controls, preserving signed links."""
    if depth > 4:
        return fail(page, "Unexpected navigation hierarchy deeper than four levels.")
    maintain_session(page)
    classes = course_controls(page)
    sections = section_controls(page) if not classes else []
    items = classes or sections
    if not items:
        res = process_course_lessons(page)
        if not res:
            return False
        if depth == 0:
            log_info("Section completed! Navigating back to continue remaining sections/courses...")
            if not click_button_by_text(page, RETURN_COURSE + [r"^Exit$", r"^Taking a Class$", r"^My Classes$"]):
                page.goto(ORACLE_HOME_URL, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
            session_wait(page, STEP_DELAY)
            return walk_courses(page, depth=0)
        return True
    kind = "course" if classes else "section"
    # Snapshot labels and indices, never reuse locators across navigation.
    labels = [item_label(item) for _, item in items]
    parent_page_url = page.url
    parent_frame = items[0][0]
    parent_frame_path = frame_path(parent_frame)
    parent_frame_url = parent_frame.url
    parent_is_main = parent_frame == page.main_frame
    for index, label in enumerate(labels):
        maintain_session(page)
        wait_until(page, lambda: len(course_controls(page) if classes else section_controls(page)) == len(labels), timeout=10)
        current = course_controls(page) if classes else section_controls(page)
        if len(current) != len(labels) or item_label(current[index][1]) != label:
            return fail(page, f"The {kind} list changed; cannot safely identify item {index + 1}.")
        before = fingerprint(page)
        log_info(f"Opening {kind} {index + 1}/{len(labels)}: {label}")
        if not safe_click(current[index][1]) or not wait_until(page, lambda: fingerprint(page) != before):
            return fail(page, f"Opening {kind} {index + 1} made no progress.")
        session_wait(page, STEP_DELAY)
        if not walk_courses(page, depth + 1):
            return False
        # Return to the saved parent using its intact, current-session URL.
        if parent_is_main:
            page.goto(parent_page_url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
        else:
            # Rebuild the shell: ancestor iframe navigation may detach a child
            # even when its old Frame object has not processed that event yet.
            page.goto("about:blank")
            page.goto(parent_page_url, wait_until="load", timeout=PAGE_LOAD_TIMEOUT)
            session_wait(page, 0.25)
            wait_until(page, lambda: resolve_frame(page, parent_frame_path) is not None)
            frame = resolve_frame(page, parent_frame_path)
            if frame is None:
                return fail(page, "Parent course frame disappeared.")
            frame.goto(parent_frame_url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
        session_wait(page, STEP_DELAY)
        if not classes:
            try:
                refreshed = section_controls(page)
                if index < len(refreshed):
                    badge = refreshed[index][1].locator('.t-MediaList-badge')
                    if badge.count():
                        percent = re.search(r'(\d+)\s*%', badge.inner_text())
                        if percent and int(percent.group(1)) < 100:
                            log_warn(f"Oracle still reports {percent.group(1)}% for {label}; moving forward.")
            except Exception:
                pass
    log_success(f"Processed all {len(labels)} {kind} entries in this list.")
    return True


def run_oracle_bot():
    from bot.groq_solver import validate_api
    validate_api()
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_PROFILE_DIR), headless=HEADLESS,
            channel=BROWSER_CHANNEL or None, no_viewport=True,
            args=["--start-maximized"])
        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(10000)
        page.on("dialog", native_dialog)
        try:
            page.goto(ORACLE_HOME_URL, timeout=PAGE_LOAD_TIMEOUT, wait_until="domcontentloaded")
            input("Sign in and open Classes or the course outline in Chrome, then press Enter here: ")
            while True:
                try:
                    if walk_courses(page):
                        log_success("Course traversal finished. Check Oracle's completion indicators for the final status.")
                        input("Press Enter to save the session and close Chrome: ")
                        break
                except SessionExpired as exc:
                    capture_diagnostic(page, str(exc))
                    log_error(str(exc))
                except Exception as exc:
                    capture_diagnostic(page, f"Runner error: {exc}")
                    log_error(str(exc))
                answer = input("Automation paused. Fix the browser state and open Classes/outline, then Enter to retry; q to quit: ")
                if answer.strip().lower() == "q":
                    raise RuntimeError("Stopped before course completion was verified.")
        finally:
            context.close()
