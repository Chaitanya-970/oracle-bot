# Project Handoff & Architecture Dossier

> Review update (10 October 2026): this dossier describes the original implementation. The maintained runner now uses bounded traversal, frame-aware question extraction, strict answer parsing, verified results, session-extension handling, and API/model preflight. The `.env` defaults have changed to `openai/gpt-oss-120b` (text) and `qwen/qwen3.8-27b` (vision) after confirming availability and inference with the user's account. Signed APEX URLs are preserved intact; removing a checksum is not a supported way to repair expired links. See `README.md` and `tests/` for current operation and verification. Local tests alone do not prove all live Oracle courses complete successfully.

**Target System:** Oracle Academy (`academy.oracle.com` - Oracle APEX Platform)  
**Project:** `oracle-bot`  
**Review Audience:** GPT-6 Astra / Senior AI Engineer  
**Date:** October 2026  

---

## 1. Executive Summary & Objectives

This project provides an automated, resilient course progression and quiz-solving pipeline for **Oracle Academy** student courses. The user is enrolled in 4 mandatory database courses:
1. **M3 Database Programming with SQL – English**
2. **M3 Database Design – English**
3. **M3 Database Foundations – English**
4. **M3 Database Programming with PLSQL – English**

### Core Requirements
- **100% Course Completion**: Every subsection within each section must be visited and marked complete (turning the sidebar indicator from an empty circle to a green checkmark `✓`).
- **Lesson Automation**: Automatically advance non-quiz content (slides, student guides, practice PDFs) by triggering the APEX `Save and Continue` or `Save Progress` actions.
- **Quiz Automation**: Detect quiz landing pages (`Take an Assessment`), dispatch the start modal, scrape questions and options from the DOM, query **Groq AI** for objectively correct answers, select the radio/checkbox choice, submit, and confirm completion.
- **Low-Latency AI Execution**: Discard local Ollama due to GPU/inference speed bottlenecks; use **Groq Cloud API** exclusively (`llama-3.3-70b-versatile` for text MCQs and `llama-3.2-11b-vision-preview` for diagram/ERD questions).
- **Forensic Diagnostic Reporting**: Instead of failing silently or throwing uncaught exceptions, capture full-page screenshots, DOM dumps, and metadata reports into `logs/diagnostics/` whenever an unexpected state occurs.

---

## 2. Architectural Evolution & Prototype Transition

Prior to the current unified architecture, two experimental prototypes were developed:

1. **`prototypes/selenium_automation/`**:
   - Initial Selenium Firefox exploration for APEX DOM scraping and choice buttons (`button.choice-SelectArea`).
   - *Limitations*: Heavy browser process overhead, high latency with local fallback models, and fragile session state recovery across multi-course dashboards.
2. **`prototypes/playwright_crawler.py`**:
   - Early Playwright proof-of-concept testing sidebar `li.t-WizardSteps-step` iteration and basic `Save and Continue` clicking.
   - *Limitations*: Covered reading steps only; lacked automated assessment parsing, Groq AI inference, and error forensics.

### The Unified Architecture (`oracle-bot`)
Both prototype approaches were superseded by a modular, production-grade Playwright application utilizing Chrome's persistent user context and Groq's high-speed cloud inference (~0.5s per question).

---

## 3. System Architecture & Components

```
c:\Users\LOQ\OneDrive\Desktop\oracle-bot\
├── bot/
│   ├── __init__.py
│   ├── config.py              # Environment variables, file paths, model identifiers, timeouts
│   ├── diagnostics.py         # Forensic logging, screenshot capture, DOM serialization, JSON reports
│   ├── groq_solver.py         # Low-latency Groq client for text and multimodal (ERD) MCQs
│   ├── apex_helpers.py        # Oracle APEX frame resolution, DOM interaction helpers
│   ├── session.py             # Active session maintenance and dialog handling
│   └── runner.py              # Master 3-tier state machine (Classes -> Sections -> Lessons/Quizzes)
├── prototypes/                # Early reference implementations (Selenium & basic Playwright scripts)
│   ├── selenium_automation/
│   └── playwright_crawler.py
├── tests/                     # Offline unit and integration test suite
│   └── test_bot.py
├── browser_profile/           # Playwright persistent context directory (preserves Oracle login cookies)
├── logs/
│   ├── bot.log                # Chronological debug and operation logs
│   └── diagnostics/           # Automated forensic artifacts on unexpected states
├── run_bot.py                 # Clean root CLI entry point
├── start.bat                  # Non-technical 1-click Windows launcher
├── .env.example / .env        # Configuration and GROQ_API_KEY storage
├── requirements.txt           # Minimal pip dependencies
├── README.md                  # Non-technical operator guide
└── handoff.md                 # Architecture documentation
```

---

## 4. Oracle APEX Platform Quirks & Engineering Solutions

### 4.1. URL Structure & Checksum Invalidation
- **Pattern**: `academy.oracle.com/pls/f?p=AppId:PageId:SessionId::Request:ClearCache:ParamNames:ParamValues&cs=Checksum`
- **Quirk**: If a URL containing an expired `SessionId` or stale `cs` checksum is requested, Oracle APEX returns a fatal error or forces a login redirect.
- **Solution (`clean_apex_url`)**:
  Clears `SessionId` (position 2 of the `p` parameter) and removes the `&cs=` query parameter entirely. When requested without an expired session, APEX issues a valid session token automatically.

### 4.2. DOM Element Staleness After AJAX Actions
- **Quirk**: Clicking `Save and Continue` triggers an APEX Dynamic Action (`P15_TO_SAVE_MODULE_ID...:SAVE:`). During the AJAX cycle, the old DOM node is briefly available before being swapped, causing `StaleElementReference` or click interception errors in standard Selenium/Playwright pipelines.
- **Solution (`safe_click` & `click_button_by_text`)**:
  Employs a two-tier click strategy: first attempts standard Playwright user-simulation click with auto-scroll; if intercepted or detached, evaluates a direct JavaScript `el.click()` event on the resolved DOM node.

### 4.3. Modal Overlay Layering
- **Quirk**: When clicking `Take an Assessment`, Oracle APEX spawns a modal dialog with a `Start` button. However, underlying elements from the lesson page remain in the DOM tree, causing generic text searches to trigger background elements.
- **Solution (`is_quiz_start_modal`)**:
  Scrapes dialog containers (`.ui-dialog`, `[role='dialog']`, `.t-Dialog`) first before dispatching the `Start` click.

### 4.4. Assessment Workflow & Dynamic Page Transitions (Pages 190 & 192)
- **Landing (Page 15)**: Displays lesson wizard and assessment card (`Take an Assessment`).
- **Start Modal**: Spawns dialog with `Start` button. When clicked, APEX navigates to **Page 190 (`Take the Assessment`)**. Old frames detach during this transition.
- **Question Page (Page 190)**: Questions render under `#question-Text`. Choice buttons render as `button.choice-SelectArea` with `role="radio"` or `role="checkbox"`. Submission control is `#quiz-submit` (`Submit Answer`).
- **Score Summary (Page 192)**: Upon answering the final question, APEX navigates to **Page 192 (`Score Summary`)**, displaying `PERCENTAGE SCORED: XX%` (live test scored 93.33%). It exposes `#B80081047542606589` (`View Results`) which triggers APEX request `VIEW`, opening detailed results and the `Return to Course Lessons` / `Exit` return controls.

### 4.5. Frame Detachment & Single-Run Traversal Pipeline
- **Detached Frame Prevention**: In APEX, dynamic actions and question submissions constantly unmount and remount iframes. Unshielded `.count()` or `.all()` calls on detaching frames (e.g. background session checks for password fields) trigger `playwright._impl._errors.Error: Locator.count: Frame was detached`. All frame evaluations across `session.py`, `apex_helpers.py`, and `runner.py` are now protected by `try...except` and `not frame.is_detached()` guards, and predicate waits suppress transient detachment errors during DOM swaps.
- **Continuous Multi-Course Sweep**: If the runner starts or retries from within a specific lesson or quiz (`items == []`), it finishes that lesson/quiz, confirms completion, navigates back via `Return to Course Lessons` or `ORACLE_HOME_URL`, and recursively continues `walk_courses(page, depth=0)` so all remaining sections and courses are completed in one unbroken run.

---

## 5. Groq Model Integration & Response Parsing

### Models Used
- **Text MCQs**: `openai/gpt-oss-120b` (verified on Groq account, ~0.5s inference)
  - High accuracy on SQL, relational schemas, primary/foreign key constraints, normalization, and PL/SQL block structures.
  - Temperature set to `0.0` for deterministic outputs.
- **Diagram / ERD Questions**: `qwen/qwen3.8-27b` (verified on Groq account, ~0.4s inference)
  - Encodes screenshot into a data URL (`data:image/png;base64,...`) to interpret ERDs (crows-foot notation, entities, relationship cardinalities).

### Index Parser Pipeline (`parse_option_indices`)
The LLM is prompted to return strictly 0-based integer indices. The parser handles multiple possible representations:
1. Raw JSON list: `[1]` or `[0, 2]`.
2. Clean integer regex: `\b(\d+)\b`.
3. Option letter mapping: `A -> 0`, `B -> 1`, `C -> 2`, `D -> 3`.
4. True / False binary fallback: `True -> 0`, `False -> 1`.

---

## 6. Diagnostic & Error Telemetry System

When an unexpected screen occurs, `bot.diagnostics.capture_diagnostic()` triggers:
1. `diag_<timestamp>_screenshot.png`: High-resolution full-page screenshot.
2. `diag_<timestamp>_dom.html`: Complete HTML dump of the current document and iframe hierarchy.
3. `diag_<timestamp>_report.json`: Metadata report with URL, page title, frame URLs, and exception stack trace.
4. Terminal Alert: Formatted box with exact file locations and a gentle pause allowing manual inspection and resumption.

---

## 7. Verification & Run Instructions

```bash
# 1. Ensure dependencies are installed
pip install playwright requests python-dotenv

# 2. Configure Groq API key in .env
# Edit .env and set: GROQ_API_KEY=gsk_...

# 3. Launch the bot
python run_bot.py
# (Or double click start.bat on Windows)
```

1. Chrome opens with persistent profile `browser_profile/`.
2. Log into Oracle Academy once.
3. Press **Enter** in the terminal to engage automation.
4. Monitor terminal logs for real-time section completions and quiz question answers.
