import os
from pathlib import Path

# Base Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BROWSER_PROFILE_DIR = PROJECT_ROOT / "browser_profile"
LOGS_DIR = PROJECT_ROOT / "logs"
DIAGNOSTICS_DIR = LOGS_DIR / "diagnostics"

# Ensure directories exist
LOGS_DIR.mkdir(parents=True, exist_ok=True)
DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)

# Load .env file manually if python-dotenv is not installed
def load_env_file():
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if key and key not in os.environ:
                        os.environ[key] = val

load_env_file()

# Groq API Configuration
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_TEXT_MODEL = os.getenv("GROQ_TEXT_MODEL", "openai/gpt-oss-120b").strip()
GROQ_VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.8-27b").strip()
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1/chat/completions").strip()

# Browser Configuration
BROWSER_CHANNEL = os.getenv("BROWSER_CHANNEL", "chrome").strip()
HEADLESS = os.getenv("HEADLESS", "false").strip().lower() in ("true", "1", "yes")

# Timing / Delays (seconds)
STEP_DELAY = float(os.getenv("STEP_DELAY", "2.0"))
PAGE_LOAD_TIMEOUT = int(os.getenv("PAGE_LOAD_TIMEOUT", "45000")) # ms
ELEMENT_TIMEOUT = int(os.getenv("ELEMENT_TIMEOUT", "10000"))     # ms

# Target Starting URLs
ORACLE_HOME_URL = os.getenv("ORACLE_HOME_URL", "https://academy.oracle.com/pls/f?p=63000:100").strip()
