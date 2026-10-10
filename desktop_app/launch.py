"""Entry point for source and packaged application."""
import sys
from pathlib import Path

if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if __name__ == '__main__':
    if '--worker' in sys.argv:
        from desktop_app.worker import run
        run()
    elif '--self-test' in sys.argv:
        from desktop_app.self_test import run
        run()
    else:
        if sys.platform == 'win32':
            import ctypes
            ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
        from desktop_app.window import main
        main()
