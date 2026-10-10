#!/usr/bin/env python3
"""
Oracle Academy Automation Entry Point
Run this script to launch the Oracle Academy Course & Quiz Bot.
"""
import sys
from bot.runner import run_oracle_bot

if __name__ == "__main__":
    try:
        run_oracle_bot()
    except KeyboardInterrupt:
        print("\n[STOP] Automation stopped by user.")
    except Exception as e:
        from bot.diagnostics import log_error, capture_diagnostic
        log_error(f"Fatal error: {e}")
        capture_diagnostic(None, f"Entry point failed: {e}")
        sys.exit(1)
