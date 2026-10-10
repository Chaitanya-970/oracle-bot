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
    return re.sub(r'[\U0001F000-\U0001FAFF\u2600-\u27BF\ufe0f]', '', text).strip()


def error_reason(exc):
    return redact(str(exc)) or type(exc).__name__


def pause_message(reason):
    reason = redact(reason) or 'The current page could not be processed; no error details were returned.'
    action = ('Open Classes before selecting Continue to retry with recorded feedback.'
              if 'below the required 70%' in reason else
              'Check the browser, then select Continue to retry from the current page.')
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
    output_lock = threading.Lock()

    def emit(kind, **data):
        with output_lock:
            output.write(json.dumps({'type': kind, **data}, ensure_ascii=True) + '\n')
            output.flush()

    class Logs(logging.Handler):
        def emit(self, record):
            if record.levelno >= logging.ERROR:
                last_failure['text'] = record.getMessage()
            emit('log', level=record.levelname, text=redact(record.getMessage()))

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
    from bot.session import maintain_session, native_dialog, SessionExpired
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
                                emit('state', state='key', text='Stopped because your Groq account reached its API limit. Wait for quota to recover, or enter a key from an account with available quota. Another key on the same account shares its limit.')
                                while True:
                                    wait_for('key', page)
                                    try:
                                        groq_solver.validate_api()
                                        break
                                    except Exception as exc:
                                        emit('log', level='ERROR', text=redact(exc))
                                        emit('state', state='key', text='This key could not be verified. Enter a valid key with available quota.')
                            else:
                                emit('state', state='paused', text=pause_message(log_text))
                                wait_for('continue', page, resume_on_key='Groq' in log_text)
                    except SessionExpired as exc:
                        emit('log', level='WARNING', text=redact(exc))
                        emit('state', state='login', text='Oracle needs another sign-in. Sign in, open Classes, and select Continue.')
                        wait_for('continue', page)
                    except Exception as exc:
                        reason = error_reason(exc)
                        emit('log', level='ERROR', text=reason)
                        emit('state', state='paused', text=pause_message(reason))
                        wait_for('continue', page)
    except KeyboardInterrupt:
        emit('state', state='stopped', text='Stopped. Progress already saved in Oracle remains saved.')
    except Exception as exc:
        emit('log', level='ERROR', text=redact(exc))
        emit('state', state='error', text='The app could not start. See the error below.')
