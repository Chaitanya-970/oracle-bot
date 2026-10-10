import json
import logging
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from bot.config import LOGS_DIR, DIAGNOSTICS_DIR

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

# Setup log file
LOG_FILE = LOGS_DIR / "bot.log"

logger = logging.getLogger("OracleBot")
logger.setLevel(logging.INFO)

# Console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter("[%(asctime)s] %(message)s", datefmt="%H:%M:%S")
console_handler.setFormatter(console_formatter)

# File handler
file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
file_handler.setLevel(logging.DEBUG)
file_formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
file_handler.setFormatter(file_formatter)

logger.addHandler(console_handler)
logger.addHandler(file_handler)


def log_info(msg: str):
    logger.info(f"ℹ️  {msg}")

def log_success(msg: str):
    logger.info(f"✅ {msg}")

def log_quiz(msg: str):
    logger.info(f"📝 {msg}")

def log_warn(msg: str):
    logger.warning(f"⚠️  {msg}")

def log_error(msg: str):
    logger.error(f"❌ {msg}")


def capture_diagnostic(page, reason: str, context: dict = None) -> dict:
    """
    Captures an automated forensic snapshot whenever an unexpected situation
    or error occurs. Saves screenshot, HTML DOM dump, and metadata JSON.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    screenshot_file = DIAGNOSTICS_DIR / f"diag_{timestamp}_screenshot.png"
    html_file = DIAGNOSTICS_DIR / f"diag_{timestamp}_dom.html"
    json_file = DIAGNOSTICS_DIR / f"diag_{timestamp}_report.json"

    url = "Unknown"
    title = "Unknown"
    frames_info = []

    if page:
        try:
            url = page.url
        except Exception:
            pass
        try:
            title = page.title()
        except Exception:
            pass
        try:
            page.screenshot(path=str(screenshot_file), full_page=True)
        except Exception as e:
            logger.warning(f"Failed to capture screenshot: {e}")
        try:
            html = page.content()
            html_file.write_text(html, encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to dump DOM: {e}")
        try:
            for i, frame in enumerate(page.frames):
                frame_file = DIAGNOSTICS_DIR / f"diag_{timestamp}_frame_{i}.html"
                info = {"index": i, "name": frame.name, "url": frame.url}
                try:
                    frame_file.write_text(frame.content(), encoding="utf-8")
                    info["dom_path"] = str(frame_file)
                except Exception as exc:
                    info["error"] = str(exc)
                frames_info.append(info)
        except Exception:
            pass

    report = {
        "timestamp": timestamp,
        "reason": reason,
        "url": url,
        "title": title,
        "frames": frames_info,
        "context": context or {},
        "screenshot_path": str(screenshot_file),
        "dom_dump_path": str(html_file),
        "traceback": traceback.format_exc() if sys.exc_info()[0] else None
    }

    try:
        json_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to save diagnostic report JSON: {e}")

    # Output highly visible diagnostic alert
    border = "=" * 70
    logger.error(
        f"\n{border}\n"
        f"🚨 [DIAGNOSTIC ALERT] Unexpected state or error encountered!\n"
        f"Reason:     {reason}\n"
        f"Page URL:   {url}\n"
        f"Screenshot: {screenshot_file}\n"
        f"DOM Dump:   {html_file}\n"
        f"Report:     {json_file}\n"
        f"{border}\n"
    )

    return report
