"""Browser owner process. All Playwright calls remain on its main thread."""
import json
import logging
import os
import queue
import re
import sys
import threading
import time
from pathlib import Path


def redact(text):
    text = re.sub(r'gsk_[A-Za-z0-9]+', '[API key hidden]', str(text))
    text = re.sub(r'https?://academy\.oracle\.com\S*', '[Oracle session URL hidden]', text, flags=re.I)
    text = re.sub(r'(?im)^\s*(?:Page URL|Screenshot|DOM Dump|Report):.*$', '', text)
    return re.sub(r'[\U0001F000-\U0001FAFF\u2600-\u27BF\ufe0f]', '', text).strip()


def display_log(text):
    """Keep detailed diagnostics in the file handler, not the app window."""
    if '[DIAGNOSTIC ALERT]' in text:
        if 'Groq API limit was reached' in text:
            return None
        match = re.search(r'Reason:\s*(.*)', text)
        return 'Paused: ' + redact(match.group(1) if match else 'Unexpected browser state. Details saved in local diagnostics.')
    if 'Groq HTTP 429' in text:
        return 'Groq quota reached. Wait for quota to recover or enter a replacement key with available quota.'
    if 'Groq API limit was reached' in text:
        return 'Groq quota reached. Wait for quota to recover or enter a replacement key with available quota.'
    return redact(text)


class RecoveryBudget:
    """Bound automatic retries for the same operation and saved page state."""
    def __init__(self):
        self.counts = {}

    def next_delay(self, reason, state):
        if not re.search(r'lesson controls|Incomplete sidebar lesson|Save action|confirm saving|Save and Continue control|selection state|Answer selection|View Results|results-navigation waits|Return to Course did not leave|TimeoutError|frame was detached|execution context was destroyed', reason, re.I):
            return None
        if re.search(r'Groq|API limit|below the required 70%|question changed|did not advance', reason, re.I):
            return None
        key = (reason, state)
        count = self.counts.get(key, 0)
        if count >= 3 or (key not in self.counts and len(self.counts) >= 128):
            return None
        self.counts[key] = count + 1
        return (5, 15, 30)[count]


def error_reason(exc):
    return redact(str(exc)) or type(exc).__name__


def pause_message(reason):
    reason = redact(reason) or 'The current page could not be processed; no error details were returned.'
    if 'below the required 70%' in reason:
        action = 'Open Classes before selecting Continue to retry with recorded feedback.'
    elif re.search(r'View Results|return-to-course|Return to Course', reason, re.I):
        action = 'Your assessment was submitted. Select View Results in Oracle and wait for the results page, then select Continue here. Do not start another quiz attempt.'
    elif re.search(r'lesson|sidebar|Save and Continue', reason, re.I):
        action = 'Wait for the lesson to finish loading. If the PDF failed to load, use Reload in its viewer. When Save and Continue is available, select Continue in this app.'
    elif re.search(r'answer.*selection|selection state', reason, re.I):
        action = 'Wait for Oracle to finish updating the selected answer, then select Continue. The bot has not submitted this answer.'
    else:
        action = 'Look for an Oracle sign-in prompt or load error in the bot\'s browser. Resolve it or wait for the page to finish loading, then select Continue.'
    return f'Paused: {reason}\n{action}'


def replacement_ready(command, validate, emit):
    """A replacement resumes an API pause only after successful validation."""
    if command.get('action') != 'key':
        return False
    try:
        validate()
    except Exception as exc:
        emit('log', level='ERROR', text=redact(exc))
        emit('state', state='key', text='This key could not be verified. Enter a valid replacement key.')
        return False
    emit('log', level='INFO', text='Replacement key verified. Resuming from the current question.')
    return True


def run():
    from desktop_app import runtime_config as config
    from desktop_app.engine import bot as engine
    sys.modules['bot'] = engine
    sys.modules['bot.config'] = config
    # The packaged driver resolves Chromium relative to the bundled package.
    if getattr(sys, 'frozen', False):
        os.environ['PLAYWRIGHT_BROWSERS_PATH'] = '0'
    output = sys.stdout
    commands = queue.Queue()
    last_failure = {'text': ''}
    stopped = threading.Event()
    recovery = RecoveryBudget()
    output_lock = threading.Lock()

    def emit(kind, **data):
        with output_lock:
            output.write(json.dumps({'type': kind, **data}, ensure_ascii=True) + '\n')
            output.flush()

    class Logs(logging.Handler):
        def emit(self, record):
            if record.levelno >= logging.ERROR:
                last_failure['text'] = record.getMessage()
            visible = display_log(record.getMessage())
            if visible:
                emit('log', level='WARNING' if 'Groq quota reached' in visible else record.levelname, text=visible)

    def read_commands():
        for line in sys.stdin:
            try:
                command = json.loads(line)
                if command.get('action') == 'key':
                    config.set_api_key(command.get('key', ''))
                if command.get('action') == 'stop':
                    stopped.set()
                commands.put(command)
            except (ValueError, TypeError):
                emit('log', level='ERROR', text='An app command could not be read.')
        stopped.set()
        commands.put({'action': 'stop'})

    threading.Thread(target=read_commands, daemon=True).start()
    from bot import diagnostics, runner, groq_solver
    from bot.session import maintain_session, native_dialog, SessionExpired, session_wait
    from playwright.sync_api import sync_playwright
    from bot import session
    original_check = maintain_session

    def checked_session(page):
        if stopped.is_set():
            raise KeyboardInterrupt
        return original_check(page)

    session.maintain_session = checked_session
    runner.maintain_session = checked_session
    for handler in list(diagnostics.logger.handlers):
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
            diagnostics.logger.removeHandler(handler)
    diagnostics.logger.addHandler(Logs())

    def recover_loading(page, reason):
        try:
            identity = runner.question_identity(page)
            active = tuple(item.inner_text(timeout=1000) for _, item in runner.wizard_steps(page)
                           if runner.is_step_active(item))
            state = repr(identity) if identity else repr((active, runner.page_text(page)[:500]))
        except Exception:
            return False  # A closed/unreadable page needs explicit recovery.
        delay = recovery.next_delay(reason, state)
        if delay is None:
            return False
        emit('state', state='recovering', text=f'Oracle is slow to respond. Retrying automatically in {delay} seconds; no Continue click is needed.')
        session_wait(page, delay)
        return True
    # Reject daily-quota exhaustion immediately in this desktop snapshot.
    # The user can replace the key in the app without restarting Chrome.

    def wait_for(action, page=None, resume_on_key=False):
        while True:
            if page is not None:
                try:
                    maintain_session(page)
                except SessionExpired:
                    pass  # The visible prompt is already asking for sign-in.
                except Exception as exc:
                    emit('log', level='WARNING', text=redact(exc))
            try:
                command = commands.get(timeout=.25)
            except queue.Empty:
                continue
            if command.get('action') == 'stop':
                raise KeyboardInterrupt
            if resume_on_key and replacement_ready(command, groq_solver.validate_api, emit):
                return command
            if command.get('action') == action:
                return command

    def verified_key(page=None):
        while True:
            emit('state', state='key', text='Enter your Groq API key, then select Use key.')
            wait_for('key', page)
            try:
                groq_solver.validate_api()
                return
            except Exception as exc:
                emit('log', level='ERROR', text=redact(exc))

    try:
        verified_key()
        with sync_playwright() as pw:
            with pw.chromium.launch_persistent_context(
                str(config.BROWSER_PROFILE_DIR), headless=False, no_viewport=True
            ) as context:
                page = context.pages[0] if context.pages else context.new_page()
                page.set_default_timeout(10000)
                def browser_dialog(dialog):
                    emit('log', level='WARNING', text='Oracle browser message: ' + redact(dialog.message))
                    native_dialog(dialog)
                page.on('dialog', browser_dialog)
                page.goto(config.ORACLE_HOME_URL, wait_until='domcontentloaded', timeout=45000)
                emit('state', state='login', text='Sign in to Oracle in the browser and open Classes. Then select Continue.')
                wait_for('continue', page)
                while True:
                    try:
                        last_failure['text'] = ''
                        emit('state', state='running', text='Working through your enrolled courses. Progress appears below.')
                        if (not runner.course_controls(page) and not runner.wizard_steps(page)
                                and not runner.section_controls(page) and not runner.is_assessment_question_page(page)):
                            runner.wait_until(page, lambda: bool(runner.course_controls(page) or runner.section_controls(page) or runner.wizard_steps(page)))
                        if runner.run_all_courses(page):
                            emit('state', state='complete', text='Finished. Congratulations! All courses in this run were processed. If you liked Oracle Bot, please star the repository: https://github.com/Chaitanya-970/oracle-bot')
                            wait_for('stop', page)
                        else:
                            log_text = last_failure['text']
                            if 'Groq API limit was reached' in log_text:
                                emit('state', state='key', text='Groq quota reached. Wait for quota to recover, or enter a replacement key with available quota and select Use key. Keys in the same organization share quota.')
                                while True:
                                    wait_for('key', page)
                                    try:
                                        groq_solver.validate_api()
                                        break
                                    except Exception as exc:
                                        emit('log', level='ERROR', text=redact(exc))
                                        emit('state', state='key', text='This key could not be verified. Enter a valid key with available quota.')
                            else:
                                if recover_loading(page, log_text):
                                    continue
                                emit('state', state='paused', text=pause_message(log_text))
                                wait_for('continue', page, resume_on_key='Groq' in log_text)
                    except SessionExpired as exc:
                        emit('log', level='WARNING', text=redact(exc))
                        emit('state', state='login', text='Oracle needs another sign-in. Sign in, open Classes, and select Continue.')
                        wait_for('continue', page)
                    except Exception as exc:
                        reason = error_reason(exc)
                        emit('log', level='ERROR', text=reason)
                        try:
                            if recover_loading(page, reason):
                                continue
                        except SessionExpired:
                            emit('state', state='login', text='Oracle needs another sign-in. Sign in, open Classes, and select Continue.')
                            wait_for('continue', page)
                            continue
                        emit('state', state='paused', text=pause_message(reason))
                        wait_for('continue', page)
    except KeyboardInterrupt:
        emit('state', state='stopped', text='Stopped. Progress already saved in Oracle remains saved.')
    except Exception as exc:
        emit('log', level='ERROR', text=redact(exc))
        emit('state', state='error', text='The app could not start. See the error below.')
