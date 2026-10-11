"""Bounded course traversal with verified transitions and explicit failures."""
import re
import json
from playwright.sync_api import sync_playwright
from bot.config import BROWSER_PROFILE_DIR, BROWSER_CHANNEL, HEADLESS, STEP_DELAY, PAGE_LOAD_TIMEOUT, ORACLE_HOME_URL
from bot.diagnostics import log_info, log_success, log_warn, log_error, capture_diagnostic
from bot.apex_helpers import (safe_click, click_button_by_text, matching_button,
    is_assessment_question_page, is_quiz_landing_page, is_quiz_start_modal,
    extract_question_and_options, visible_locators, page_text, question_identity,
    wizard_steps, step_complete, is_step_active, is_multiple_choice_question)
from bot.groq_solver import solve_with_session
from bot.session import maintain_session, session_wait, wait_until, native_dialog, SessionExpired

from bot.recovery import RecoveryBudget, recovery_state

LAST_FAILURE = ""

RETURN_COURSE = [r"^Return to Course Lessons$", r"^Return to Course$", r"^Course Outline$", r"^Exit$", r"^Course$"]
RESULTS = r"Results Summary|Assessment Score|Assessment (?:is )?Complete|Score Summary|Percentage Scored|Mastery Score"


def fail(page, reason):
    global LAST_FAILURE
    LAST_FAILURE = reason
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
        if not click_button_by_text(page, [r"^Complete Assessment$", r"^Submit Assessment$"]):
            return fail(page, "Assessment results were not confirmed and no completion control was found.")
        session_wait(page, 0.5)
        click_button_by_text(page, [r"^Complete Assessment$", r"^Submit Assessment$", r"^Yes$", r"^Confirm$"], modal_only=True)
        if not wait_until(page, lambda: bool(re.search(RESULTS, page_text(page), re.I))):
            return fail(page, "Assessment submission did not reach a score/results screen.")

    from bot.assessment_results import record_results
    score = record_results(page)

    # Retry only results navigation, never submission or starting a new attempt.
    for attempt in range(3):
        if matching_button(page, RETURN_COURSE) is not None:
            break
        if attempt:
            log_info(f"Oracle results are still loading; retrying View Results ({attempt + 1}/3).")
        click_button_by_text(page, [r"^View Results$"])
        if wait_until(page, lambda: matching_button(page, RETURN_COURSE) is not None, timeout=15):
            break
    else:
        return fail(page, "The assessment was submitted, but Oracle did not load its return-to-course control after three results-navigation waits. Select View Results in the browser, wait for the results page, then select Continue. Do not start a new assessment.")

    result_score = record_results(page)
    score = result_score if result_score is not None else score
    if not click_button_by_text(page, RETURN_COURSE):
        return fail(page, "Results reached, but Return to Course was not found.")
    if not wait_until(page, lambda: bool(wizard_steps(page) or section_controls(page) or course_controls(page))):
        return fail(page, "Return to Course did not leave the assessment results.")
    if score is not None and score < 70:
        target = getattr(page, '_oracle_quiz_retry', None)
        if not target:
            return fail(page, f"Assessment scored {score}%, below the required 70%. Feedback recorded, but this resumed quiz's original lesson link is unavailable. Open that quiz before continuing.")
        if target['retries'] >= 2:
            return fail(page, f"Assessment scored {score}%, below the required 70% after two automatic retries. Feedback recorded. The course is already open; review the quiz before continuing.")
        target['retries'] += 1
        log_info(f"Assessment scored {score}%. Reopening only this quiz automatically (retry {target['retries']}/2) using recorded feedback.")
        page.goto(target['url'], wait_until='domcontentloaded', timeout=PAGE_LOAD_TIMEOUT)
        if not wait_until(page, lambda: is_quiz_landing_page(page)):
            return fail(page, "Could not reopen the original quiz for automatic retry. Open that quiz in Oracle before continuing.")
        return handle_quiz_landing_and_start(page, retry=True)
    if hasattr(page, '_oracle_quiz_retry'):
        del page._oracle_quiz_retry
    log_success("Assessment submitted; results confirmed and returned to course.")
    return True



def selection_matches(locators, indices):
    for i, loc in enumerate(locators):
        state = loc.get_attribute("aria-checked", timeout=1000)
        if state is not None and (state == "true") != (i in indices):
            return False
    return True


def lesson_control_ready(page):
    if matching_button(page, [r"^Save and Continue$", r"^Save Progress$"]) is not None:
        return True
    if is_quiz_landing_page(page) or is_assessment_question_page(page) or is_quiz_start_modal(page):
        return True
    steps = wizard_steps(page)
    return bool(steps and all(step_complete(item) for _, item in steps))


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
        from bot.config import LOGS_DIR
        with (LOGS_DIR / 'questions.jsonl').open('a', encoding='utf-8') as audit:
            audit.write(json.dumps({'identity': identity, 'question': text, 'options': options, 'multiple': multiple}, ensure_ascii=False) + '\n')
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
        if not multiple and len(indices) > 1:
            return fail(page, "Multiple answers returned for a single-choice question; nothing submitted.")
        for i, loc in enumerate(locators):
            checked = loc.get_attribute("aria-checked") == "true"
            if (i in indices and not checked) or (multiple and i not in indices and checked):
                if not safe_click(loc):
                    return fail(page, f"Could not select/deselect answer {i}.")
        # Oracle may update aria-checked asynchronously after a successful click.
        # Wait without clicking again: another click could toggle a checkbox off.
        if not wait_until(page, lambda: question_identity(page) == identity and
                          selection_matches(locators, indices), timeout=10):
            return fail(page, "Answer selection did not settle within 10 seconds; no answer was submitted. Wait for Oracle to respond, then select Continue.")
        seen.add(identity)
        session_wait(page, 0.5)
        if not click_button_by_text(page, [r"^Submit Answer$", r"^Next Question$", r"^Next$"]):
            return finish_assessment(page)
        if not wait_until(page, lambda: question_identity(page) != identity or matching_button(page, [r"^Next Question$", r"^Next$"]) is not None):
            return fail(page, "Submit Answer produced no next question or feedback navigation.")
        if question_identity(page) == identity:
            if not click_button_by_text(page, [r"^Next Question$", r"^Next$"]) or not wait_until(page, lambda: question_identity(page) != identity):
                return fail(page, "Feedback screen did not advance to the next question.")
    return fail(page, "Assessment exceeded the 200-question safety limit.")


def handle_quiz_landing_and_start(page, retry=False):
    maintain_session(page)
    if not is_quiz_start_modal(page):
        target = getattr(page, '_oracle_quiz_retry', None)
        if not retry and (target is None or target['url'] != page.url):
            page._oracle_quiz_retry = {'url': page.url, 'retries': 0}
        if not click_button_by_text(page, [r"^Take an Assessment$", r"^Finish Assessment$", r"^Resume Assessment$"]):
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
        # Returning from results can leave a completed quiz's start control
        # visible. Consult the sidebar before opening another attempt.
        if (is_quiz_landing_page(page) and
                any(is_step_active(item) and step_complete(item) for _, item in steps)):
            remaining = [item for _, item in steps if not step_complete(item)]
            if remaining:
                before = fingerprint(page)
                target = remaining[0]
                link = target.locator("a.t-WizardSteps-wrap, a, .t-WizardSteps-label").first
                log_info("Skipping completed assessment; opening the next incomplete sidebar item.")
                if not (safe_click(link) or safe_click(target)):
                    return fail(page, "Could not leave the completed assessment.")
                if not wait_until(page, lambda: fingerprint(page) != before):
                    return fail(page, "Completed assessment navigation made no progress.")
                continue
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
        if (incomplete and is_step_active(incomplete[0]) and
                "is-incomplete-assessment" not in (incomplete[0].get_attribute("class") or "") and
                not lesson_control_ready(page)):
            log_info("Waiting for Oracle lesson controls to finish loading (up to 60 seconds).")
            if wait_until(page, lambda: lesson_control_ready(page), timeout=60):
                continue  # Reacquire sidebar state after the delayed render.
            return fail(page, "Oracle lesson controls did not become ready within 60 seconds. If the PDF says Failed to load PDF document, reload that lesson or check your connection. Wait for Save and Continue to become available, then select Continue.")
        if incomplete:
            target = incomplete[0]
            # If the first incomplete step is not already the active step, jump directly to it!
            if not is_step_active(target):
                link = target.locator("a.t-WizardSteps-wrap, a, .t-WizardSteps-label").first
                log_info(f"Jumping directly to incomplete step ({len(incomplete)} remaining in section)...")
                try:
                    link.scroll_into_view_if_needed(timeout=2000)
                except Exception:
                    pass
                if not (safe_click(link) or safe_click(target)):
                    return fail(page, "Could not jump to the incomplete sidebar step.")
                if not wait_until(page, lambda: fingerprint(page) != before):
                    return fail(page, "Jump to the incomplete sidebar step made no progress.")
                continue

        if incomplete and "is-incomplete-assessment" in (incomplete[0].get_attribute("class") or ""):
            if wait_until(page, lambda: is_quiz_landing_page(page) or is_assessment_question_page(page) or is_quiz_start_modal(page)):
                continue
            return fail(page, "Incomplete assessment opened without a usable assessment control.")

        save_control = matching_button(page, [r"^Save and Continue$", r"^Save Progress$"])
        if save_control is not None:
            clicked = safe_click(save_control)
            # A click can time out after dispatch while Oracle still navigates.
            # Observe the result instead of reopening the same sidebar lesson.
            if not wait_until(page, lambda: fingerprint(page) != before, timeout=30):
                reason = ("Oracle did not confirm saving this lesson within 30 seconds." if clicked else
                          "Oracle's Save and Continue control could not be clicked and the lesson did not advance.")
                return fail(page, reason + " Wait for the lesson to finish loading, then select Continue to retry. No completion was assumed.")
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
        return process_course_lessons(page)
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
        if not classes:
            try:
                badge = current[index][1].locator('.t-MediaList-badge, [class*="badge"]')
                if not badge.count():
                    badge = current[index][1].locator('xpath=ancestor::li[1]').locator('.t-MediaList-badge, [class*="badge"]')
                badge_text = badge.first.inner_text() if badge.count() else ""
                pct = re.search(r'(\d+)\s*%', badge_text)
                if pct and int(pct.group(1)) == 100:
                    log_success(f"Skipping {label} (already 100% complete).")
                    continue
            except Exception:
                pass
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
                            return fail(page, f"Oracle still reports {percent.group(1)}% for {label}; section completion was not confirmed.")
            except Exception as exc:
                return fail(page, f"Could not verify section status for {label}: {exc}")
    log_success(f"Processed all {len(labels)} {kind} entries in this list.")
    return True


def run_all_courses(page):
    """Finish an in-progress section once, then perform one dashboard sweep."""
    maintain_session(page)
    if not course_controls(page):
        if not section_controls(page) and not process_course_lessons(page):
            return False
        page.goto(ORACLE_HOME_URL, wait_until='domcontentloaded', timeout=PAGE_LOAD_TIMEOUT)
        if not wait_until(page, lambda: bool(course_controls(page))):
            return fail(page, 'Could not reach the Classes dashboard to run all courses.')
    return walk_courses(page)


def run_oracle_bot():
    global LAST_FAILURE
    recovery = RecoveryBudget()
    from bot.groq_solver import validate_api
    validate_api()
    with sync_playwright() as p:
        try:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(BROWSER_PROFILE_DIR), headless=HEADLESS,
                channel=BROWSER_CHANNEL or None, no_viewport=True,
                args=["--start-maximized"])
        except Exception as exc:
            if "profile is already in use" in str(exc).lower() or "existing browser session" in str(exc).lower():
                log_warn("A Chrome window is already using this profile. Please close Chrome and press Enter to retry.")
                input("Close all Chrome windows opened by the bot, then press Enter to continue: ")
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(BROWSER_PROFILE_DIR), headless=HEADLESS,
                    channel=BROWSER_CHANNEL or None, no_viewport=True,
                    args=["--start-maximized"])
            else:
                raise

        # Clean up any blank/extra tabs opened automatically by Chrome
        for extra in list(context.pages)[1:]:
            try:
                if extra.url in ("about:blank", "chrome://newtab/", ""):
                    extra.close()
            except Exception:
                pass

        page = context.pages[0] if context.pages else context.new_page()
        page.bring_to_front()
        page.set_default_timeout(10000)
        page.on("dialog", native_dialog)
        try:
            if page.url in ("about:blank", ""):
                page.goto(ORACLE_HOME_URL, timeout=PAGE_LOAD_TIMEOUT, wait_until="domcontentloaded")
            input("Sign in and open Classes or the course outline in Chrome, then press Enter here: ")
            while True:
                LAST_FAILURE = ""
                try:
                    if run_all_courses(page):
                        log_success("Course traversal finished. Check Oracle's completion indicators for the final status.")
                        input("Press Enter to save the session and close Chrome: ")
                        break
                except SessionExpired as exc:
                    LAST_FAILURE = str(exc)
                    capture_diagnostic(page, str(exc))
                    log_error(str(exc))
                except Exception as exc:
                    LAST_FAILURE = str(exc) or type(exc).__name__
                    capture_diagnostic(page, f"Runner error: {exc}")
                    log_error(str(exc))
                try:
                    delay = recovery.next_delay(LAST_FAILURE, recovery_state(page))
                    if delay is not None:
                        log_info(f"Oracle is slow to respond. Retrying automatically in {delay} seconds; no Enter press is needed.")
                        session_wait(page, delay)
                        continue
                except SessionExpired:
                    log_warn("Oracle needs another sign-in before continuing.")
                except Exception as exc:
                    log_warn(f"Automatic recovery could not inspect the page: {exc}")
                answer = input("Automation paused. Fix the browser state and open Classes/outline, then Enter to retry; q to quit: ")
                if answer.strip().lower() == "q":
                    raise RuntimeError("Stopped before course completion was verified.")
        finally:
            context.close()
