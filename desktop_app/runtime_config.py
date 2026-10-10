"""Desktop-only configuration, stored outside the installed application."""
import os
import sys
from pathlib import Path

if os.getenv('ORACLE_DESKTOP_DATA'):
    PROJECT_ROOT = Path(os.environ['ORACLE_DESKTOP_DATA']).resolve()
elif sys.platform == 'win32':
    PROJECT_ROOT = Path(os.getenv('LOCALAPPDATA', str(Path.home()))) / 'OracleBot'
elif sys.platform == 'darwin':
    PROJECT_ROOT = Path.home() / 'Library' / 'Application Support' / 'OracleBot'
else:
    PROJECT_ROOT = Path(os.getenv('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'OracleBot'
BROWSER_PROFILE_DIR = PROJECT_ROOT / 'browser_profile'
LOGS_DIR = PROJECT_ROOT / 'logs'
DIAGNOSTICS_DIR = LOGS_DIR / 'diagnostics'
for directory in (PROJECT_ROOT, LOGS_DIR, DIAGNOSTICS_DIR):
    directory.mkdir(parents=True, exist_ok=True)
GROQ_API_KEY = ''
GROQ_TEXT_MODEL = 'openai/gpt-oss-120b'
GROQ_VISION_MODEL = 'qwen/qwen3.8-27b'
GROQ_BASE_URL = 'https://api.groq.com/openai/v1/chat/completions'
BROWSER_CHANNEL = ''
HEADLESS = False
STEP_DELAY = 2.0
PAGE_LOAD_TIMEOUT = 45000
ELEMENT_TIMEOUT = 10000
ORACLE_HOME_URL = 'https://academy.oracle.com/pls/f?p=63000:100'


def current_api_key():
    return GROQ_API_KEY


def set_api_key(value):
    global GROQ_API_KEY
    GROQ_API_KEY = value.strip()
