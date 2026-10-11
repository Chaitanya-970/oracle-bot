"""Offline package smoke check, with no Oracle login or Groq requests."""
import json
import os
import sys
import tempfile
import subprocess
from pathlib import Path


def run():
    with tempfile.TemporaryDirectory(prefix='oracle-desktop-check-') as folder:
        os.environ['ORACLE_DESKTOP_DATA'] = folder
        os.environ['PLAYWRIGHT_BROWSERS_PATH'] = '0'
        from desktop_app import runtime_config
        from desktop_app.engine import bot as engine
        sys.modules['bot'] = engine
        sys.modules['bot.config'] = runtime_config
        from bot.apex_helpers import is_step_active
        from playwright.sync_api import sync_playwright
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        from desktop_app.window import App
        app = App(root)
        app.events.put({'type': 'state', 'state': 'key', 'text': 'API key required'})
        app.events.put({'type': 'log', 'level': 'INFO', 'text': 'Solving Question 3 of 15'})
        app.poll()
        assert app.status.get() == 'API key required'
        assert str(app.use_key['state']) == 'normal'
        assert str(app.key['show']) == '*'
        assert app.progress['value'] == 20
        app.events.put({'type': 'state', 'state': 'running', 'text': 'Rate limited by Groq. Waiting before retrying...'})
        app.events.put({'type': 'log', 'level': 'INFO', 'text': 'Groq answered in 0.5s'})
        app.poll()
        assert app.status.get().startswith('Working')
        app.events.put({'type': 'state', 'state': 'paused', 'text': 'Needs attention'})
        app.poll()
        assert not app.repo_link.winfo_manager()
        app.events.put({'type': 'state', 'state': 'complete', 'text': 'Finished. Congratulations!'})
        app.poll()
        assert app.progress['value'] == 100
        assert app.repo_link.winfo_manager() == 'pack'
        assert app.repo_link.cget('text') == 'https://github.com/Chaitanya-970/oracle-bot'
        assert app.repo_link.bind('<Button-1>')
        assert app.log.tk.call(app.log._w, 'tag', 'bind', 'repository', '<Button-1>')
        assert 'Finished' in app.detail.get()
        app.events.put({'type': 'state', 'state': 'recovering', 'text': 'Retrying automatically in 5 seconds; no Continue click is needed.'})
        app.poll()
        assert str(app.continue_button['state']) == 'disabled'
        assert 'automatically' in app.status.get()
        root.destroy()
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content('<li class="t-WizardSteps-step is-active-module">Current</li>')
            assert is_step_active(page.locator('li'))
            browser.close()
        command = [sys.executable, '--worker'] if getattr(sys, 'frozen', False) else [sys.executable, str(Path(__file__).with_name('launch.py')), '--worker']
        child = subprocess.run(command, input='{"action":"stop"}\n', capture_output=True, text=True, timeout=30, env=dict(os.environ))
        assert child.returncode == 0, child.stderr
        events = [json.loads(line) for line in child.stdout.splitlines()]
        assert any(event.get('state') == 'key' for event in events), events
        assert any(event.get('state') == 'stopped' for event in events), events
        print(json.dumps({'ok': True, 'window': True, 'bundled_browser': True, 'engine': True, 'worker_protocol': True}))
