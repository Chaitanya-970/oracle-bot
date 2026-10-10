"""Interactive review harness: reload fixes without discarding Oracle login."""
import importlib
from playwright.sync_api import sync_playwright
from bot.config import BROWSER_PROFILE_DIR, ORACLE_HOME_URL
from bot.diagnostics import capture_diagnostic
from bot.groq_solver import validate_api
from bot.session import native_dialog
import bot.runner
import bot.apex_helpers
import bot.session
import bot.groq_solver


def main():
    validate_api()
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(str(BROWSER_PROFILE_DIR), channel='chrome', headless=False, no_viewport=True)
        page = context.pages[0]
        page.on('dialog', native_dialog)
        page.goto(ORACLE_HOME_URL, wait_until='domcontentloaded')
        try:
            while True:
                command = input('Review command (inspect / run / section / exit): ').strip()
                if command == 'exit':
                    break
                for module in (bot.apex_helpers, bot.session, bot.groq_solver, bot.runner):
                    importlib.reload(module)
                try:
                    if command == 'inspect':
                        capture_diagnostic(page, 'Live project review snapshot')
                    elif command == 'run':
                        print('Traversal result:', bot.runner.run_all_courses(page))
                    elif command == 'section':
                        print('Section result:', bot.runner.process_course_lessons(page))
                    elif command.startswith('goto '):
                        page.goto(command[5:], wait_until='domcontentloaded')
                except Exception as exc:
                    capture_diagnostic(page, f'Live review: {exc}')
        finally:
            context.close()


if __name__ == '__main__':
    main()
