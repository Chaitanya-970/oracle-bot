"""Visible, frame-aware Oracle APEX interactions."""
import base64
import re
from html import unescape
from urllib.parse import urljoin


def clean_apex_url(url: str) -> str:
    # Removing a checksum cannot repair an expired protected APEX link.
    return url


def surfaces(page):
    return [frame for frame in page.frames if not frame.is_detached()]


def option_text(value):
    # APEX's aria-label can itself contain escaped HTML entities and <br> tags.
    for _ in range(3):
        decoded = unescape(value)
        if decoded == value:
            break
        value = decoded
    return re.sub(r'</?(?:br|p|div|span|b|strong|em|i|pre|code)(?:\s[^>]*)?\s*/?>', '\n', value, flags=re.I).strip()


def visible_locators(page, selector):
    for frame in surfaces(page):
        try:
            loc = frame.locator(selector)
            for i in range(loc.count()):
                item = loc.nth(i)
                if item.is_visible():
                    yield frame, item
        except Exception:
            continue


def find_in_frames(page, selector):
    return next(visible_locators(page, selector), (None, None))


def safe_click(locator, timeout=4000):
    try:
        if not locator.is_visible() or not locator.is_enabled():
            return False
        locator.click(timeout=timeout)
        return True
    except Exception:
        return False


def matching_button(page, patterns, modal_only=False):
    for frame in surfaces(page):
        try:
            if frame.is_detached():
                continue
            dialogs = frame.locator(".ui-dialog:visible, [role='dialog']:visible, .t-Dialog:visible")
            if modal_only:
                if not dialogs.count():
                    continue
                roots = [dialogs.nth(i) for i in range(dialogs.count())]
            else:
                roots = [dialogs.nth(i) for i in range(dialogs.count())] + [frame]
            for root in roots:
                controls = root.locator("button, a, input[type='button'], input[type='submit']")
                # One DOM snapshot instead of several browser round trips for
                # every control, including duplicate button-label spans.
                indices = controls.evaluate_all("""(elements, patterns) => {
                    const expressions = patterns.map(p => new RegExp(p, 'i'));
                    return elements.flatMap((el, i) => {
                        const text = (el.tagName === 'INPUT' ? el.value : el.innerText)
                            || el.getAttribute('aria-label') || '';
                        if (!el.getClientRects().length || getComputedStyle(el).visibility === 'hidden'
                            || el.disabled || el.getAttribute('aria-disabled') === 'true') return [];
                        return expressions.some(re => re.test(text.trim())) ? [i] : [];
                    });
                }""", patterns)
                for index in indices:
                    el = controls.nth(index)
                    if el.is_visible() and el.is_enabled():
                        return el
        except Exception:
            continue
    return None


def click_button_by_text(page, text_patterns, modal_only=False):
    loc = matching_button(page, text_patterns, modal_only)
    return loc is not None and safe_click(loc)


def page_text(page):
    texts = []
    for frame in surfaces(page):
        try:
            texts.append(frame.locator("body").inner_text(timeout=2000))
        except Exception:
            pass
    return "\n".join(texts)


def question_identity(page):
    for frame in surfaces(page):
        try:
            body = frame.locator("body").inner_text(timeout=2000)
            match = re.search(r"Question\s+(\d+)\s+of\s+(\d+)", body, re.I)
            if match:
                regions = frame.locator('[region-id="question-Text"]:visible, [id*="question-Text"]:visible')
                text = regions.first.inner_text() if regions.count() else body
                # APEX removes its reset-pagination flag after rendering.
                # That URL cleanup does not change the assessment question.
                stable_url = frame.url.replace(":RP:", "::")
                return (stable_url, match.group(0), text)
        except Exception:
            pass
    return None


def is_assessment_question_page(page):
    return question_identity(page) is not None


def is_quiz_landing_page(page):
    return not is_assessment_question_page(page) and matching_button(page, [r"^Take an Assessment$", r"^Finish Assessment$", r"^Resume Assessment$"]) is not None


def is_quiz_start_modal(page):
    return matching_button(page, [r"^Start$"], modal_only=True) is not None


def extract_question_and_options(page):
    for frame in surfaces(page):
        try:
            if frame.is_detached():
                continue
            choices = frame.locator("button.choice-SelectArea:visible")
            if choices.count() < 2:
                choices = frame.locator('[role="radio"]:visible, [role="checkbox"]:visible')
            if choices.count() < 2:
                continue
            options, locators = [], []
            for i in range(choices.count()):
                choice = choices.nth(i)
                label = option_text(choice.get_attribute("aria-label") or choice.inner_text())
                if label:
                    options.append(label)
                    locators.append(choice)
            regions = frame.locator('[region-id="question-Text"]:visible, [id*="question-Text"]:visible')
            image = None
            if regions.count():
                region = regions.first
                text = region.inner_text().strip()
                for img in region.locator("img:visible, svg:visible, canvas:visible").all():
                    box = img.bounding_box()
                    if box and box["width"] >= 40 and box["height"] >= 40:
                        image = base64.b64encode(region.screenshot()).decode("ascii")
                        break
            else:
                body = frame.locator("body").inner_text()
                match = re.search(r"Question\s+\d+\s+of\s+\d+([\s\S]+?)(?=Submit Answer|Next Question|$)", body, re.I)
                text = match.group(1).strip() if match else ""
            return text, image, options, locators
        except Exception:
            continue
    return "", None, [], []


def wizard_steps(page):
    return list(visible_locators(page, "li.t-WizardSteps-step"))


def step_complete(step):
    try:
        classes = (step.get_attribute("class") or "").split()
        return ("is-complete" in classes or "is-complete-assessment" in classes or
                step.locator(".fa-check, .fa-check-circle, .fa-check-circle-o, [class*='check']").count() > 0)
    except Exception:
        return False


def is_step_active(step):
    try:
        # Oracle sets aria-current on every entry; its module class identifies
        # the actual displayed lesson. Prefer that explicit marker globally.
        state = step.evaluate("""el => {
            const active = el.ownerDocument.querySelector('li.t-WizardSteps-step.is-active-module');
            if (active) return active === el;
            const markers = ['is-active', 'is-selected', 'is-current', 'active'];
            const link = el.querySelector('a, .t-WizardSteps-wrap');
            if (markers.some(c => el.classList.contains(c) || link?.classList.contains(c))) return true;
            if (link?.href === el.ownerDocument.location.href) return true;
            const marked = [...el.ownerDocument.querySelectorAll('li.t-WizardSteps-step')]
                .filter(item => [item, item.querySelector('a')].some(node =>
                    ['step', 'page', 'true'].includes(node?.getAttribute('aria-current'))));
            return marked.length === 1 && marked[0] === el;
        }""")
        return bool(state)
    except Exception:
        return False


def is_multiple_choice_question(page, question_text, locators):
    for loc in locators:
        try:
            resp_type = loc.get_attribute("data-response-type")
            if resp_type == "1":
                return False
            if resp_type == "2":
                return True
            role = loc.get_attribute("role")
            if role == "radio":
                return False
            if role == "checkbox":
                return True
        except Exception:
            continue
    full_text = f"{question_text} {page_text(page)}"
    if re.search(r"just one correct", full_text, re.I):
        return False
    return bool(re.search(r"select all that apply|choose (?:two|three|four|five|all|\d+)|which (?:two|three|four|five|\d+)", full_text, re.I))
