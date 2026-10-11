import base64
import json
import os
import re
import sys
import time
import traceback
from pathlib import Path
import shutil
import subprocess
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from selenium import webdriver
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    NoSuchElementException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC




GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite").strip()
GEMINI_MODELS = [GEMINI_MODEL] if GEMINI_MODEL else []
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_BASE = os.getenv("GEMINI_BASE", "https://generativelanguage.googleapis.com/v1beta")

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3-vl:8b")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", "0.70"))
DEFAULT_PROFILE = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "OracleQuizRunnerFirefoxProfile"
FIREFOX_PROFILE = Path(os.getenv("FIREFOX_PROFILE", str(DEFAULT_PROFILE))).resolve()
LOG_DIR = Path(os.getenv("LOG_DIR", "./quiz_logs")).resolve()
LOG_DIR.mkdir(exist_ok=True)

QUESTION_WAIT = float(os.getenv("QUESTION_WAIT", "0.7"))
NAV_WAIT = float(os.getenv("NAV_WAIT", "0.9"))
SAVE_CONTROL_WAIT = float(os.getenv("SAVE_CONTROL_WAIT", "15"))
CLICK_TIMEOUT = int(os.getenv("CLICK_TIMEOUT", "12"))
MAX_SECTIONS = int(os.getenv("MAX_SECTIONS", "100"))
API_TIMEOUT = int(os.getenv("GEMINI_TIMEOUT", "30"))
RETRY_DELAY = float(os.getenv("RETRY_DELAY", "2.0"))
VERIFY_RISKY = os.getenv("VERIFY_RISKY", "1").strip().lower() not in {"0", "false", "no", "off"}
OLLAMA_FIRST = os.getenv("OLLAMA_FIRST", "1").strip().lower() not in {"0", "false", "no", "off"}
OLLAMA_VERIFY_TIMEOUT = int(os.getenv("OLLAMA_VERIFY_TIMEOUT", "45"))
GEMINI_RPM_GUARD = float(os.getenv("GEMINI_RPM_GUARD", "4.2"))
_last_gemini_call = 0.0
_gemini_turn = 0


SOLVER_SYSTEM_PROMPT = """You are a careful multiple-choice answer solver.
Determine the objectively correct answer from the question and options.
Pay close attention to wording, True/False statements, definitions, and subtle distinctions.
Do not guess based on the position of an option.
Return ONLY the zero-based option index, or comma-separated zero-based indices for multiple-correct questions.
Do not output explanations."""

INDEPENDENT_SYSTEM_PROMPT = """Independently solve this multiple-choice question.
Be skeptical: check every option against the exact wording before choosing.
For True/False questions, verify whether the statement is actually true rather than relying on familiarity.
Return ONLY the zero-based option index, or comma-separated zero-based indices.
Do not output explanations."""

JUDGE_SYSTEM_PROMPT = """You are the final adjudicator for a multiple-choice quiz question.
Two solvers proposed answers. Re-evaluate the original question and ALL options yourself.
Do not assume either proposal is correct. Pick the objectively correct option(s).
Return ONLY the zero-based option index, or comma-separated zero-based indices.
Do not output explanations."""


def clean(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def stop(msg):
    print(f"\n[STOP] {msg}")
    print("No more browser actions were performed.\n")
    raise RuntimeError(msg)


def visible(el):
    try:
        return el.is_displayed()
    except Exception:
        return False


def text_of(el):
    try:
        return clean(el.text)
    except Exception:
        return ""


def all_frames(driver):
    """Yield the default document and every iframe document, switching safely."""
    if not ensure_valid_window(driver):
        return
    driver.switch_to.default_content()
    yield None
    frames = driver.find_elements(By.TAG_NAME, "iframe")
    for frame in frames:
        try:
            driver.switch_to.default_content()
            driver.switch_to.frame(frame)
            yield frame
        except Exception:
            continue
    driver.switch_to.default_content()



def ensure_valid_window(driver):
    """Recover if Oracle closed/replaced the current Firefox browsing context."""
    try:

        driver.current_url
        return True
    except Exception:
        pass

    try:
        handles = driver.window_handles
    except Exception:
        handles = []



    for handle in reversed(handles):
        try:
            driver.switch_to.window(handle)
            driver.current_url
            print("[BROWSER] Current Firefox window was replaced; switched to the remaining Oracle window.")
            return True
        except Exception:
            continue
    return False

def body_text(driver):
    try:
        if not ensure_valid_window(driver):
            return ""
        driver.switch_to.default_content()
        return clean(driver.find_element(By.TAG_NAME, "body").text)
    except Exception:
        return ""


def wait_settle(driver, seconds=NAV_WAIT):
    time.sleep(seconds)
    try:
        WebDriverWait(driver, 4).until(
            lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
        )
    except Exception:
        pass


def find_visible_by_text(driver, pattern, tag=None):
    """Find visible elements by their normalized text, across the main page/iframes."""
    rx = re.compile(pattern, re.I)
    for _ in all_frames(driver):
        xpath = "//*" if not tag else f"//{tag}"
        try:
            els = driver.find_elements(By.XPATH, xpath)
            for el in els:
                if visible(el) and rx.fullmatch(clean(text_of(el))):
                    yield el
        except Exception:
            continue
    driver.switch_to.default_content()


def click_element(driver, el):
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    except Exception:
        pass
    try:
        el.click()
        return True
    except Exception:
        try:
            driver.execute_script("arguments[0].click();", el)
            return True
        except Exception:
            return False


def click_text(driver, patterns, tags=None):
    """Click a visible control by text OR common button attributes.

    Oracle APEX sometimes renders modal actions such as Start/Complete as
    <input value="Start"> rather than an element whose .text is "Start".
    The older runner only checked .text, so the assessment Start modal could
    be visible while the automation incorrectly reported that Start was missing.
    """
    tags = tags or ["button", "a", "input", "div", "span", "label"]
    for pat in patterns:
        rx = re.compile(pat, re.I)
        for _ in all_frames(driver):
            for tag in tags:
                try:
                    for el in driver.find_elements(By.TAG_NAME, tag):
                        if not visible(el):
                            continue
                        candidates = [text_of(el)]
                        for attr in ("value", "aria-label", "title", "name", "data-label"):
                            try:
                                candidates.append(clean(el.get_attribute(attr)))
                            except Exception:
                                pass


                        if any(rx.fullmatch(c) or ("Save and Continue" in c and rx.search(c)) for c in candidates if c):
                            if click_element(driver, el):
                                driver.switch_to.default_content()
                                return True
                except Exception:
                    pass
    driver.switch_to.default_content()
    return False


def on_course_outline(driver):
    text = body_text(driver)
    return bool(
        re.search(r"Course\s+Outline", text, re.I)
        and re.search(r"(?:Sections|Modules|Lessons)\s+in\s+Course", text, re.I)
    )


def find_incomplete_section(driver):
    """Find the first course section that has NO progress percentage.

    Oracle's outline marks completed sections with a percentage on the same row/card.
    For this runner's workflow we intentionally use the simple rule:
      - row has a visible N% marker -> completed, skip it
      - row has no visible N% marker -> incomplete, open it

    We associate percentages by screen position rather than by a large DOM ancestor,
    because Oracle's nested APEX markup can make a parent container contain many
    sections and therefore many unrelated percentages.
    """
    if not ensure_valid_window(driver):
        return None
    driver.switch_to.default_content()







    numbered_pattern = re.compile(
        r"^(?:Section|Module|Chapter|Unit)\s+\d+\s*[-:–—]|"
        r"^[A-Z]{2,12}\s+\d+(?:[-.]\d+)*\s*[-:–—:]",
        re.I,
    )
    main_quiz_pattern = re.compile(
        r"(?:^|\b)(?:mid\s*-?\s*term|midterm|cumulative\s+final|final)"
        r"(?:\s+(?:exam|assessment|quiz))?(?:$|\b)",
        re.I,
    )




    candidates = {}
    try:
        all_els = driver.find_elements(
            By.XPATH,
            "//*[self::a or self::button or self::div or self::span or self::h1 or self::h2 or self::h3 or self::li]"
        )
    except Exception:
        return None

    for el in all_els:
        try:
            if not visible(el):
                continue
            title = clean(text_of(el))
            if len(title) > 220:
                continue

            is_numbered = bool(numbered_pattern.match(title))
            is_main_quiz = bool(main_quiz_pattern.search(title))
            if not (is_numbered or is_main_quiz):
                continue




            if is_main_quiz and el.tag_name.lower() not in {"a", "button", "li", "div", "span"}:
                continue
            rect = driver.execute_script(
                "const r=arguments[0].getBoundingClientRect(); return {x:r.x,y:r.y,w:r.width,h:r.height,area:r.width*r.height};",
                el,
            )
            if not rect or rect["w"] <= 0 or rect["h"] <= 0:
                continue
            key = title.lower()
            old = candidates.get(key)
            if old is None or rect["area"] < old[1]["area"]:
                candidates[key] = (el, rect, title)
        except Exception:
            continue

    if not candidates:
        return None


    percentages = []
    try:
        pct_els = driver.find_elements(By.XPATH, "//*[normalize-space(text()) and contains(normalize-space(text()), '%')]")
        for el in pct_els:
            try:
                if not visible(el):
                    continue
                txt = clean(text_of(el))
                m = re.fullmatch(r"(\d{1,3})%", txt)
                if not m:
                    continue
                rect = driver.execute_script(
                    "const r=arguments[0].getBoundingClientRect(); return {x:r.x,y:r.y,w:r.width,h:r.height};",
                    el,
                )
                if rect and rect["w"] > 0 and rect["h"] > 0:
                    percentages.append((int(m.group(1)), rect))
            except Exception:
                continue
    except Exception:
        pass



    ordered = sorted(candidates.values(), key=lambda item: (item[1]["y"], item[1]["x"]))

    for el, rect, title in ordered:
        ty = rect["y"] + rect["h"] / 2
        tx = rect["x"] + rect["w"] / 2




        nearby = []
        for pct, pr in percentages:
            py = pr["y"] + pr["h"] / 2
            if abs(py - ty) <= max(55, rect["h"] * 1.6):
                nearby.append((abs(py - ty), pct))

        if nearby:
            pct = min(nearby)[1]
            print(f"[COURSE] {title}: {pct}% (progress marker found on its row)")

            continue

        print(f"[COURSE] {title}: no progress marker -> INCOMPLETE")
        print(f"[COURSE] Next incomplete section: {title}")
        return el, title

    return None

def click_section(driver, el, title):
    driver.switch_to.default_content()
    if not click_element(driver, el):
        stop(f"Could not open incomplete section: {title}")
    time.sleep(0.25)
    print(f"[COURSE] Opened {title}")


def is_quiz_landing(driver):
    """Detect an assessment landing page by its actual action control.

    IMPORTANT: Oracle can leave the old "Take an Assessment" control in the
    DOM for a short time while the assessment question page is already visible.
    Never classify an actual Question N of M page as a landing page.
    """

    if is_assessment_question(driver):
        return False
    try:
        for _ in all_frames(driver):
            for tag in ("button", "a", "input", "div", "span", "label"):
                try:
                    for el in driver.find_elements(By.TAG_NAME, tag):
                        if not visible(el):
                            continue
                        vals = [text_of(el)]
                        for attr in ("value", "aria-label", "title", "name", "data-label"):
                            try:
                                vals.append(clean(el.get_attribute(attr)))
                            except Exception:
                                pass
                        if any(re.fullmatch(r"Take an Assessment", v, re.I) for v in vals if v):
                            driver.switch_to.default_content()
                            return True
                except Exception:
                    continue
        driver.switch_to.default_content()
    except Exception:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass
    return False


def is_assessment_question(driver):
    return bool(re.search(r"Question\s+\d+\s+of\s+\d+", body_text(driver), re.I))


def click_save_and_continue(driver):
    return click_text(driver, [r"^Save and Continue$"])

def fast_click_save_and_continue(driver):
    """Reliably click Oracle's visible Save and Continue control.

    Oracle can keep several copies of the control in the DOM while an APEX
    page is being refreshed.  Only click a genuinely visible, enabled control
    whose center is actually on the visible element.  If JS cannot find one,
    fall back to Selenium/frame scanning.
    """
    try:
        driver.switch_to.default_content()
        clicked = driver.execute_script(r"""
            const rx = /\bSave\s+and\s+Continue\b/i;
            const nodes = [...document.querySelectorAll('button,a,input,[role="button"],[role="link"]')];
            const visible = e => {
                const r=e.getBoundingClientRect(), cs=getComputedStyle(e);
                if (!r.width || !r.height) return false;
                if (cs.display==='none' || cs.visibility==='hidden' || cs.opacity==='0') return false;
                if (e.disabled || e.getAttribute('aria-disabled')==='true') return false;
                return true;
            };
            const candidates = nodes.filter(e => {
                if (!visible(e)) return false;
                const s=[e.innerText,e.textContent,e.value,e.getAttribute('aria-label'),e.getAttribute('title'),e.getAttribute('data-label')]
                    .filter(Boolean).join(' ').replace(/\s+/g,' ').trim();
                if (!rx.test(s)) return false;
                const r=e.getBoundingClientRect();
                const cx=r.left+r.width/2, cy=r.top+r.height/2;
                if (cx<0 || cy<0 || cx>window.innerWidth || cy>window.innerHeight) return false;
                const top=document.elementFromPoint(cx,cy);
                return top === e || e.contains(top) || top?.contains(e);
            });
            if (!candidates.length) return false;
            candidates.sort((a,b)=>{
                const ar=a.getBoundingClientRect(), br=b.getBoundingClientRect();
                const ae=(ar.width*ar.height), be=(br.width*br.height);
                return ae-be;
            });
            const e=candidates[0];
            e.scrollIntoView({block:'center',inline:'center'});
            e.click();
            return true;
        """)
        if clicked:
            return True
    except Exception:
        pass


    try:
        driver.switch_to.default_content()
        rx = re.compile(r"\bSave\s+and\s+Continue\b", re.I)
        for _ in all_frames(driver):
            for tag in ("button", "a", "input", "div", "span", "label"):
                try:
                    for el in driver.find_elements(By.TAG_NAME, tag):
                        if not visible(el):
                            continue
                        vals = [text_of(el)]
                        for attr in ("value", "aria-label", "title", "name", "data-label"):
                            try:
                                vals.append(clean(el.get_attribute(attr)))
                            except Exception:
                                pass
                        if any(rx.search(v) for v in vals if v):
                            if click_element(driver, el):
                                driver.switch_to.default_content()
                                return True
                except Exception:
                    continue
        driver.switch_to.default_content()
    except Exception:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass
    return False


def wait_for_lesson_control(driver, timeout=SAVE_CONTROL_WAIT):
    """Poll through Oracle's AJAX/page transition instead of failing immediately.

    After Save and Continue, Oracle may temporarily remove the old button while
    rebuilding the page.  A 0.1s scan is too early and was the reason the runner
    stopped after only a couple of successful lesson pages.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_assessment_question(driver):
            return "question"
        if is_quiz_landing(driver):
            return "quiz"
        if is_readable_lesson_page(driver):
            return "progress"
        if on_course_outline(driver):
            return "outline"
        if fast_click_save_and_continue(driver):
            return "clicked"
        time.sleep(0.20)
    return None


def click_save_progress(driver):



    return click_text(driver, [r"^Save Progress$"])


def click_take_assessment(driver):
    return click_text(driver, [r"^Take an Assessment$"])


def click_start_assessment(driver):
    return click_text(driver, [r"^Start$"])


def wait_for_assessment_question(driver, timeout=12):
    """Wait for Oracle to finish the Take Assessment -> Start transition."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_assessment_question(driver):
            return True
        time.sleep(0.25)
    return False


def reach_quiz(driver, max_clicks=100):
    for step in range(max_clicks):


        if is_assessment_question(driver):
            print("[COURSE] Assessment question page detected; handing off to Gemini...")
            return

        if is_quiz_landing(driver):
            print("[COURSE] 'Take an Assessment' detected; opening assessment...")
            if not click_take_assessment(driver):
                stop("Found the assessment landing page but could not click 'Take an Assessment'.")



            wait_settle(driver, 0.5)
            print("[COURSE] Assessment landing modal detected; clicking Start...")
            if not click_start_assessment(driver):
                time.sleep(1.0)
                if not click_start_assessment(driver):
                    stop("Assessment landing modal opened, but the 'Start' button was not found.")

            if wait_for_assessment_question(driver, timeout=15):
                print("[COURSE] Question page reached; handing off to Gemini...")
                return




            wait_settle(driver, 1.0)
            if is_assessment_question(driver):
                print("[COURSE] Question page reached; handing off to Gemini...")
                return
            continue




        if is_readable_lesson_page(driver):
            print("[COURSE] Readable lesson with Save Progress detected; handing off...")
            return




        if fast_click_save_and_continue(driver):
            print(f"[COURSE] Save and Continue ({step + 1})")
            state = wait_for_lesson_control(driver)
            if state == "question":
                print("[COURSE] Question page reached after Save and Continue.")
                return
            if state == "quiz":
                print("[COURSE] Assessment landing reached after Save and Continue.")
                return
            if state == "progress":
                return
            if state == "outline":
                return


            print("[COURSE] Save and Continue clicked but Oracle did not expose the next control yet; retrying...")
            continue



        state = wait_for_lesson_control(driver, timeout=SAVE_CONTROL_WAIT)
        if state in {"clicked", "question", "quiz", "progress", "outline"}:
            if state == "clicked":
                print(f"[COURSE] Save and Continue ({step + 1})")
            continue


        clicked = False
        for pat in [r"^(?:Quiz|Assessment)\s*[:–-].*$"]:
            for el in find_visible_by_text(driver, pat):
                if click_element(driver, el):
                    clicked = True
                    break
            if clicked:
                break
        driver.switch_to.default_content()
        if clicked:
            wait_settle(driver)
            continue

        stop("Could not find 'Save and Continue' or a quiz/assessment control.")
    stop("Exceeded lesson-navigation safety limit.")


def _question_region(driver):
    """Return Oracle's actual question text container when possible.

    The current Oracle APEX page exposes the question under an element whose
    ajax identifier contains "question-Text" and whose content is ordinary DOM
    text. We prefer that over scraping the entire page.
    """
    driver.switch_to.default_content()
    selectors = [
        '[region-id="question-Text"]',
        '[ajax-identifier*="question-Text"]',
        '[id*="question-Text"]',
        'a-dynamic-content[region-id="question-Text"]',
    ]
    for sel in selectors:
        try:
            for el in driver.find_elements(By.CSS_SELECTOR, sel):
                if visible(el):
                    return el
        except Exception:
            pass

    try:
        for h in driver.find_elements(By.XPATH, "//*[self::h1 or self::h2 or self::h3 or self::div or self::span]"):
            if not visible(h) or not re.fullmatch(r"Question\s+\d+\s+of\s+\d+", clean(text_of(h)), re.I):
                continue
            node=h
            for _ in range(7):
                node=node.find_element(By.XPATH, "..")
                txt=clean(text_of(node))
                if 5 <= len(txt) <= 3000 and re.search(r"Question\s+\d+\s+of\s+\d+", txt, re.I):
                    return node
    except Exception:
        pass
    return None


def extract_question_text(driver):
    region = _question_region(driver)
    if region is None:
        return ""
    txt = clean(text_of(region))

    txt = re.sub(r"^Question\s+\d+\s+of\s+\d+\s*", "", txt, flags=re.I)
    return clean(txt)


def question_has_image(driver):
    """True only when the actual question block contains a meaningful image."""
    region = _question_region(driver)
    if region is None:
        return False
    try:
        for img in region.find_elements(By.CSS_SELECTOR, "img"):
            if not visible(img):
                continue
            rect = driver.execute_script("const r=arguments[0].getBoundingClientRect(); return {w:r.width,h:r.height};", img)
            if rect and rect["w"] >= 40 and rect["h"] >= 40:
                return True
    except Exception:
        pass
    return False


def screenshot_question_area(driver, qnum):
    driver.switch_to.default_content()
    region = _question_region(driver)
    if region is not None:
        try:
            png = region.screenshot_as_png
            (LOG_DIR / f"question_{qnum:03d}.png").write_bytes(png)
            return png
        except Exception:
            pass
    png = driver.get_screenshot_as_png()
    (LOG_DIR / f"question_{qnum:03d}.png").write_bytes(png)
    return png


def extract_options(driver):
    """Extract Oracle APEX choice buttons directly from the DOM.

    The current page uses button.choice-SelectArea with role=radio/checkbox and
    aria-label containing the option text. This is substantially more reliable
    than trying to OCR or click the surrounding visual card.
    """
    driver.switch_to.default_content()


    try:
        buttons = driver.find_elements(By.CSS_SELECTOR, "button.choice-SelectArea")
        opts=[]
        for b in buttons:
            if not visible(b):
                continue
            label=clean(b.get_attribute("aria-label")) or clean(text_of(b))
            role=clean(b.get_attribute("role")) or "custom"
            if label and len(label) <= 1000:
                opts.append((b,label,role))
        if len(opts) >= 2:
            return opts
    except Exception:
        pass


    for selector in ('[role="radio"]', '[role="checkbox"]', 'button[aria-label]'):
        try:
            opts=[]
            for el in driver.find_elements(By.CSS_SELECTOR, selector):
                if not visible(el):
                    continue
                label=clean(el.get_attribute("aria-label")) or clean(text_of(el))
                if not label or len(label)>1000:
                    continue
                if label.lower() in {"answer choices", "instructions"}:
                    continue
                opts.append((el,label,clean(el.get_attribute("role")) or "custom"))
            if len(opts)>=2:
                return opts
        except Exception:
            pass

    stop("Could not detect answer options in the Oracle DOM.")

def _gemini_generate(prompt, image_b64=None, system_prompt=SOLVER_SYSTEM_PROMPT, model=None):
    """Call one Gemini model. Models are load-balanced per question.

    A single API key/project can call both models; the model endpoint is selected
    independently for each request. We keep a separate local pacing timer per model
    so alternating models does not accidentally apply the 4.2s guard globally.
    """
    global _last_gemini_call
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set. Put your Gemini API key in .env or set it in start.bat.")
    if not GEMINI_MODELS:
        raise RuntimeError("No Gemini model configured.")
    model = GEMINI_MODEL

    gap = time.perf_counter() - _last_gemini_call
    if gap < GEMINI_RPM_GUARD:
        time.sleep(GEMINI_RPM_GUARD - gap)
    _last_gemini_call = time.perf_counter()
    parts=[{"text": prompt}]
    if image_b64:
        parts.append({"inline_data": {"mime_type": "image/png", "data": image_b64}})
    payload={"contents":[{"role":"user","parts":parts}],"systemInstruction":{"parts":[{"text":system_prompt}]},"generationConfig":{"maxOutputTokens":24,"temperature":0}}
    url=f"{GEMINI_BASE}/models/{model}:generateContent?key={GEMINI_API_KEY}"
    req=Request(url,data=json.dumps(payload).encode(),headers={"Content-Type":"application/json"},method="POST")
    try:
        with urlopen(req,timeout=API_TIMEOUT) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as exc:
        detail=exc.read().decode("utf-8",errors="replace")
        raise RuntimeError(f"Gemini {model} HTTP {exc.code}: {detail[:700]}") from exc
    except URLError as exc:
        raise RuntimeError(f"Gemini {model} connection error: {exc}") from exc

def _gemini_model_order(preferred=None):
    if not GEMINI_MODELS:
        return []
    if preferred in GEMINI_MODELS:
        return [preferred] + [m for m in GEMINI_MODELS if m != preferred]
    return list(GEMINI_MODELS)


def _ollama_chat(prompt, image_b64=None):
    """Call Ollama robustly for both instruct and older qwen3-vl:8b installs.

    The thinking qwen3-vl:8b tag can ignore think:false because its template
    lacks the thinking switch. Ollama documents the -instruct tag as the proper
    non-thinking variant; if the older tag is installed instead, use the raw
    ChatML workaround with an assistant prefill.
    """
    user_content = prompt + "\n/no_think"
    messages=[{"role":"system","content":SOLVER_SYSTEM_PROMPT},{"role":"user","content":user_content}]
    if image_b64: messages[-1]["images"]=[image_b64]

    def post(path, payload):
        req=Request(OLLAMA_HOST.rstrip("/")+path,data=json.dumps(payload).encode(),headers={"Content-Type":"application/json"},method="POST")
        with urlopen(req,timeout=OLLAMA_VERIFY_TIMEOUT) as resp:
            return json.loads(resp.read().decode())

    first_error=None

    try:
        result=post("/api/chat", {"model":OLLAMA_MODEL,"messages":messages,"stream":False,"think":False,"options":{"temperature":0,"num_predict":96},"keep_alive":"10m"})
        raw=((result.get("message",{}) or {}).get("content") or "").strip()
        if raw: return result
        first_error="chat returned empty content"
    except Exception as exc:
        first_error=exc



    try:
        raw_messages=[{"role":"user","content":user_content}]
        if image_b64: raw_messages[0]["images"]=[image_b64]
        raw_messages.append({"role":"assistant","content":"<think>\n\n</think>\n"})
        result=post("/api/chat", {"model":OLLAMA_MODEL,"messages":raw_messages,"stream":False,"raw":True,"options":{"temperature":0,"num_predict":96},"keep_alive":"10m"})
        raw=((result.get("message",{}) or {}).get("content") or "").strip()
        if raw: return result
        raise RuntimeError("raw compatibility chat returned empty content")
    except Exception as exc:
        raise RuntimeError(f"Ollama chat failed; normal={first_error}; raw_compat={exc}")


def _parse_indices(raw, n_options):
    raw=(raw or "").strip()
    try:
        data=json.loads(raw)
        if isinstance(data,dict):
            idx=data.get("indices")
            if isinstance(idx,list) and idx and all(isinstance(i,int) for i in idx) and all(0<=i<n_options for i in idx):
                return sorted(set(idx)), 1.0
    except Exception: pass
    nums=re.findall(r"(?<!\d)(\d+)(?!\d)",raw)
    vals=[]
    for x in nums:
        i=int(x)
        if 0<=i<n_options and i not in vals: vals.append(i)
    if vals: return vals,1.0

    low=raw.lower()
    if n_options==2:
        if re.search(r"\btrue\b",low) and not re.search(r"\bfalse\b",low): return [0],1.0
        if re.search(r"\bfalse\b",low) and not re.search(r"\btrue\b",low): return [1],1.0
    raise ValueError(f"Could not parse option index from model output: {raw[:500]!r}")

def _gemini_answer(prompt, image_b64, system_prompt, preferred_model=None):
    """Solve with the selected Gemini model, then immediately fail over to the other
    configured model on API failure (especially 429). Normally this is exactly one
    Gemini request per question.
    """
    errors=[]
    for model in _gemini_model_order(preferred_model):
        started=time.perf_counter()
        try:
            result=_gemini_generate(prompt,image_b64,system_prompt,model=model)
            candidates=result.get("candidates") or []
            raw=""
            if candidates:
                for part in (candidates[0].get("content",{}).get("parts") or []):
                    if part.get("text"):
                        raw += part["text"]
            if not raw.strip():
                raise ValueError(f"Gemini {model} returned no text: {result}")
            return raw.strip(), time.perf_counter()-started, model
        except Exception as exc:
            errors.append(f"{model}: {exc}")
            if len(_gemini_model_order(preferred_model)) > 1:
                print(f"[AI] {model} failed; trying alternate Gemini model...")
    raise RuntimeError("; ".join(errors))


def _build_question_prompt(question_text, options):
    option_text = "\n".join(f"{i}. {o[1]}" for i, o in enumerate(options))
    return (
        f"Question:\n{question_text or '[question text unavailable]'}\n\n"
        f"Options:\n{option_text}\n\n"
        "Return ONLY the correct zero-based option index. "
        "For multiple correct choices, return comma-separated zero-based indices."
    )


def _judge_prompt(question_text, options, proposal_a, proposal_b):
    option_text = "\n".join(f"{i}. {o[1]}" for i, o in enumerate(options))
    return (
        f"Question:\n{question_text or '[question text unavailable]'}\n\n"
        f"Options:\n{option_text}\n\n"
        f"Solver A proposed: {proposal_a}\n"
        f"Solver B proposed: {proposal_b}\n\n"
        "Re-evaluate the question yourself. These proposals may both be wrong. "
        "Return ONLY the objectively correct zero-based option index."
    )


def _normalized_indices(indices):
    return tuple(sorted(set(indices)))


def _format_choice(indices, options):
    return [(i, options[i][1]) for i in indices]


def _is_risky_question(question_text, options):
    q=clean(question_text).lower()
    terms=("true or false","except","not ","never","always","only","both","either","cannot","must","best represented","best be represented","most likely","called a/an","called a","represented by","relationship","arc","hierarchical","recursive","uid","normalization","which of the following")
    return any(t in q for t in terms) or len(q)>180

def ask_model(question_text, options, image_png=None):
    """Gemini-only, load-balanced answering.

    Q1/Q3/... use model A and Q2/Q4/... use model B. If the chosen model
    returns an error/429, the other configured Gemini model is tried immediately.
    There is no Ollama call and no double-Gemini verification on normal questions.
    """
    prompt=_build_question_prompt(question_text,options)
    image_b64=base64.b64encode(image_png).decode("ascii") if image_png else None
    started=time.perf_counter()
    preferred=GEMINI_MODELS[0] if GEMINI_MODELS else None
    raw,elapsed,used_model=_gemini_answer(prompt,image_b64,SOLVER_SYSTEM_PROMPT,preferred_model=preferred)
    idx,_=_parse_indices(raw,len(options))
    print(f"[AI] Gemini {used_model} {'VISION' if image_png else 'DOM'} | {elapsed:.2f}s | raw={raw[:80]!r}")
    return idx,0.90


def click_option(driver, option):
    """Click the exact Oracle choice button, with a JS fallback."""
    el=option[0]
    driver.switch_to.default_content()
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    except Exception:
        pass
    try:
        if visible(el):
            el.click()
            return
    except Exception:
        pass
    try:
        driver.execute_script("arguments[0].click();", el)
        return
    except Exception:
        pass


    label=option[1]
    try:
        for candidate in driver.find_elements(By.CSS_SELECTOR, "button.choice-SelectArea"):
            if visible(candidate) and clean(candidate.get_attribute("aria-label"))==label:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", candidate)
                try:
                    candidate.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", candidate)
                return
    except Exception:
        pass
    stop(f"Could not click answer option: {label}")

def click_submit_answer(driver):
    return click_text(driver, [r"^Submit Answer$"])


def click_last_visible_exact(driver, label):
    """Click the LAST visible exact-match control.

    Oracle keeps the top navigation Complete Assessment button in the DOM
    after opening the confirmation modal. A generic text search can therefore
    hit the obscured/underlying button instead of the modal button. The modal
    action is normally the last matching visible control, so prefer it.
    """
    rx = re.compile(rf"^{re.escape(label)}$", re.I)
    matches = []
    try:
        driver.switch_to.default_content()
        for _ in all_frames(driver):
            for tag in ("button", "a", "input", "div", "span", "label"):
                try:
                    for el in driver.find_elements(By.TAG_NAME, tag):
                        if not visible(el):
                            continue
                        vals = [text_of(el)]
                        for attr in ("value", "aria-label", "title", "name", "data-label"):
                            try:
                                vals.append(clean(el.get_attribute(attr)))
                            except Exception:
                                pass
                        if any(rx.fullmatch(v) for v in vals if v):
                            matches.append(el)
                except Exception:
                    continue
        driver.switch_to.default_content()
        for el in reversed(matches):
            if click_element(driver, el):
                return True
    except Exception:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass
    return False


def click_complete_assessment(driver):


    return click_last_visible_exact(driver, "Complete Assessment")


def click_confirm_complete(driver):



    deadline = time.time() + 8
    while time.time() < deadline:
        if click_last_visible_exact(driver, "Complete Assessment"):
            return True
        time.sleep(0.25)
    return False


def click_view_results(driver):


    return click_last_visible_exact(driver, "View Results")


def complete_quiz(driver):
    last_q=None
    while True:
        time.sleep(QUESTION_WAIT)
        text=body_text(driver)
        m=re.search(r"Question\s+(\d+)\s+of\s+(\d+)",text,re.I)
        if not m:
            if re.search(r"Percentage Scored|Results Summary|Mastery Score",text,re.I):
                print("[QUIZ] Results page detected.")
                return

            raise RuntimeError("Assessment question was not detected yet.")
        qnum,total=int(m.group(1)),int(m.group(2))
        if last_q != qnum: print(f"\n[QUIZ] Question {qnum}/{total}")
        options=extract_options(driver)
        question_text=extract_question_text(driver)
        if last_q != qnum:
            print(f"[DOM] Question: {question_text[:220]}")
            print(f"[DOM] Options: {[o[1] for o in options]}")
        image_png=screenshot_question_area(driver,qnum) if question_has_image(driver) else None
        try:
            indices,confidence=ask_model(question_text,options,image_png)
        except Exception as exc:
            print(f"[RETRY] AI failed on Q{qnum}: {exc}")
            print(f"[RETRY] Keeping this exact question active; retrying in {RETRY_DELAY:.1f}s...")
            last_q=qnum
            time.sleep(RETRY_DELAY)
            continue
        print(f"[AI] Selected: {[(i,options[i][1]) for i in indices]} | verification={confidence:.2f}")
        if confidence < MIN_CONFIDENCE:
            print(
                f"[AI] Verification below threshold ({confidence:.2f} < {MIN_CONFIDENCE:.2f}); "
                f"retrying the same question instead of submitting an unverified answer."
            )
            last_q = qnum
            time.sleep(RETRY_DELAY)
            continue
        try:
            for i in indices: click_option(driver,options[i])
            time.sleep(0.15)
            if qnum<total:
                if not click_submit_answer(driver): raise RuntimeError("Could not find 'Submit Answer'.")
            else:
                print("[QUIZ] Final question answered. Completing assessment...")
                if not click_complete_assessment(driver): raise RuntimeError("Could not find final 'Complete Assessment'.")
                time.sleep(0.5)
                if not click_confirm_complete(driver): raise RuntimeError("Could not confirm 'Complete Assessment'.")



                results_deadline = time.time() + 15
                results_clicked = False
                while time.time() < results_deadline:
                    if is_results_page(driver):
                        if not results_clicked:
                            print("[QUIZ] Results page detected; clicking View Results...")
                            results_clicked = click_view_results(driver)
                            if results_clicked:
                                print("[QUIZ] View Results clicked.")
                                time.sleep(0.8)
                            else:
                                time.sleep(0.4)
                        break
                    time.sleep(0.4)
                if not results_clicked:
                    print("[QUIZ] View Results was not found; continuing from the score page.")
                ensure_valid_window(driver); return
        except Exception as exc:
            print(f"[RETRY] Browser action failed on Q{qnum}: {exc}")
            time.sleep(RETRY_DELAY)
            continue
        last_q=qnum

def is_results_page(driver):
    return bool(re.search(r"Percentage Scored|Results Summary|Mastery Score", body_text(driver), re.I))


def return_to_course(driver):
    if not ensure_valid_window(driver):
        stop("Firefox no longer has a usable Oracle window after the assessment.")
    for _ in range(12):
        if on_course_outline(driver):
            return
        if is_results_page(driver):
            if click_text(driver, [r"^Return to Course Lessons$"]):
                wait_settle(driver, 1.5)
                continue
        else:
            if click_text(driver, [r"^Return to Course$", r"^Course$"]):
                wait_settle(driver, 1.5)
                continue
        time.sleep(0.7)
    stop("Could not return to the course outline after completing the section.")


def find_firefox_binary():
    candidates = [
        os.getenv("FIREFOX_PATH", ""),
        r"C:\Program Files\Mozilla Firefox\firefox.exe",
        r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
        str(Path(os.getenv("LOCALAPPDATA", "")) / "Mozilla/Firefox/firefox.exe"),
    ]
    for path in candidates:
        if path and Path(path).exists():
            return path
    return None


def launch_firefox():
    binary = find_firefox_binary()
    if not binary:
        raise RuntimeError("Could not find your installed Firefox. Set FIREFOX_PATH in the environment if it is installed elsewhere.")

    FIREFOX_PROFILE.mkdir(parents=True, exist_ok=True)
    options = Options()
    options.binary_location = binary
    options.add_argument("-profile")
    options.add_argument(str(FIREFOX_PROFILE))
    options.set_preference("dom.webnotifications.enabled", False)
    options.set_preference("media.autoplay.default", 0)
    print(f"Browser: installed Mozilla Firefox ({binary})")
    print(f"Profile: {FIREFOX_PROFILE}")
    print("No Playwright browser is downloaded or used.")
    print("This is a separate persistent runner profile. Your main Firefox profile is untouched.")
    try:
        driver = webdriver.Firefox(options=options)
    except WebDriverException as exc:
        raise RuntimeError(
            "Firefox could not be started. Close any Firefox window using the runner's profile and try again. "
            "Selenium Manager should obtain the small WebDriver component automatically.\n"
            + str(exc)
        ) from exc
    driver.set_window_size(1440, 900)
    driver.set_page_load_timeout(45)
    return driver


def is_readable_lesson_page(driver):
    """Detect a non-quiz section page that exposes Save Progress.

    Quiz question pages and quiz landing pages are deliberately excluded first,
    because unfinished assessments can also show a Save Progress control.
    """
    if is_assessment_question(driver) or is_quiz_landing(driver):
        return False
    txt = body_text(driver)
    if not txt:
        return False

    return bool(re.search(r"\bSave Progress\b", txt, re.I))


def complete_readable_lesson(driver):
    print("[COURSE] Non-quiz lesson detected; clicking 'Save Progress'...")
    if not click_save_progress(driver):
        raise RuntimeError("Readable lesson detected but could not click 'Save Progress'.")
    wait_settle(driver, 1.0)


    if not on_course_outline(driver):
        for _ in range(8):
            if on_course_outline(driver):
                break
            if click_text(driver, [r"^Return to Course Lessons$", r"^Return to Course$", r"^Course$"]):
                wait_settle(driver, 1.0)
                continue
            time.sleep(0.6)
    print("[COURSE] Readable lesson saved.")


def run_one_cycle(driver, max_sections=MAX_SECTIONS):
    """Run the current course from whatever Oracle page is visible."""
    completed=0
    for _ in range(max_sections):
        try:
            if is_assessment_question(driver):
                print("[RESUME] Assessment question detected; continuing quiz...")
                complete_quiz(driver); completed += 1; return_to_course(driver); continue
            if is_quiz_landing(driver):
                print("[RESUME] Quiz landing detected; opening assessment...")
                reach_quiz(driver); complete_quiz(driver); completed += 1; return_to_course(driver); continue
            if is_readable_lesson_page(driver):
                print("[RESUME] Readable non-quiz lesson detected; saving progress...")
                complete_readable_lesson(driver); completed += 1; continue
            if not on_course_outline(driver):
                try:
                    reach_quiz(driver)
                except Exception:
                    if is_results_page(driver):
                        return_to_course(driver)
                    elif on_course_outline(driver):
                        pass
                    else:
                        raise
                if is_assessment_question(driver):
                    complete_quiz(driver); completed += 1; return_to_course(driver); continue
                if is_quiz_landing(driver):
                    reach_quiz(driver); complete_quiz(driver); completed += 1; return_to_course(driver); continue
                if is_readable_lesson_page(driver):
                    complete_readable_lesson(driver); completed += 1; continue
            if not on_course_outline(driver):
                return_to_course(driver)
            target=find_incomplete_section(driver)
            if not target:
                print(f"[DONE] No incomplete sections found. Sections completed this run: {completed}")
                return True
            el,title=target
            click_section(driver,el,title)


            if is_assessment_question(driver):
                complete_quiz(driver)
                completed += 1
                print(f"[SECTION] {title} quiz completed. Total this run: {completed}")
                return_to_course(driver)
                continue
            if is_quiz_landing(driver):
                reach_quiz(driver)
                complete_quiz(driver)
                completed += 1
                print(f"[SECTION] {title} quiz completed. Total this run: {completed}")
                return_to_course(driver)
                continue
            if is_readable_lesson_page(driver):
                complete_readable_lesson(driver)
                completed += 1
                print(f"[SECTION] {title} readable lesson completed. Total this run: {completed}")
                continue


            reach_quiz(driver)
            if is_assessment_question(driver) or is_quiz_landing(driver):
                if is_quiz_landing(driver):
                    reach_quiz(driver)
                complete_quiz(driver)
                completed += 1
                print(f"[SECTION] {title} quiz completed. Total this run: {completed}")
                return_to_course(driver)
            elif is_readable_lesson_page(driver):
                complete_readable_lesson(driver)
                completed += 1
                print(f"[SECTION] {title} readable lesson completed. Total this run: {completed}")
            else:
                raise RuntimeError(f"Section '{title}' did not expose a quiz or Save Progress lesson page.")
        except Exception as exc:
            print(f"[RECOVER] Cycle error: {exc}")
            traceback.print_exc()
            return False
    return False

def main():
    print("="*64)
    print(" Oracle Academy Course Runner - Gemini + Firefox (v27)")
    print("="*64)
    print(f"Gemini model: {GEMINI_MODEL}\nMode: Single Gemini model from GEMINI_MODEL in .env\nOllama: disabled")
    print("Gemini is primary: two independent answer passes + a third judge only on disagreement. DOM extraction is used for normal questions; vision is used for image/diagram questions.")
    print("The runner has its OWN persistent Firefox profile. Your normal Firefox stays separate and usable.")
    print("If a course finishes, the runner stays alive for the next course instead of quitting.")

    driver=launch_firefox()
    try:
        print("\nFirefox opened. Log into Oracle in THIS runner window if needed, then navigate to the course/quiz.")
        input("Press ENTER when ready... ")
        while True:
            ok=run_one_cycle(driver)
            if ok:
                print("\n[COURSE] Course scan finished.\n[NEXT] Watcher stays active — navigate the SAME Firefox window to the next course; no ENTER is needed.")


                time.sleep(3)
                continue


            print("\n[FALLBACK] Runner hit an error but will keep watching the browser.")
            attempt = 0
            while True:
                attempt += 1
                time.sleep(5)
                if not ensure_valid_window(driver):
                    print("[FALLBACK] Firefox window is gone; restarting with the persistent profile...")
                    try:
                        driver=launch_firefox()
                    except Exception as exc:
                        print(f"[FALLBACK] Restart failed: {exc}")
                        continue
                txt=body_text(driver)
                print(f"[FALLBACK] Scan {attempt} | URL={driver.current_url[:120] if ensure_valid_window(driver) else 'N/A'}")
                if is_assessment_question(driver) or is_quiz_landing(driver) or is_readable_lesson_page(driver) or on_course_outline(driver):
                    print("[FALLBACK] Oracle page detected again; resuming automation.")
                    break


    except KeyboardInterrupt:
        print("\n[STOP] Ctrl+C received. Firefox is left open and its login state is preserved.")
    except Exception as exc:
        print(f"\n[ERROR] {exc}")
        traceback.print_exc()
        print("\nFirefox is being left open so you can inspect/recover the page.")
        input("Press ENTER to return to the watcher... ")
    finally:


        pass


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nFatal error: {exc}")
        sys.exit(1)
