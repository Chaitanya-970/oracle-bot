"""Run on the target OS inside a dedicated build environment."""
import os
import subprocess
import shutil
import sys
from pathlib import Path

def main():
    root = Path(__file__).resolve().parent.parent
    output = root / 'desktop_app' / 'output'
    env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH='0')
    subprocess.run([sys.executable, '-m', 'playwright', 'install', 'chromium'], env=env, check=True)
    subprocess.run([
    sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onedir', '--console',
    '--name', 'OracleBot', '--collect-all', 'playwright', '--collect-submodules', 'desktop_app',
    '--paths', str(root), '--paths', str(root / 'desktop_app' / 'engine'),
    '--hidden-import', 'bot.runner', '--hidden-import', 'bot.assessment_results',
    '--distpath', str(output / 'dist'), '--workpath', str(output / 'build'),
    '--specpath', str(output), str(root / 'desktop_app' / 'launch.py'),
    ], env=env, check=True)
    package = output / 'dist' / 'OracleBot'
    for name in ('README.md', 'LICENSE', 'NOTICE', 'SUPPORT.md'):
        shutil.copyfile(root / name, package / name)
    if (root / 'docs').exists():
        shutil.copytree(root / 'docs', package / 'docs', dirs_exist_ok=True)
    (package / 'desktop_app').mkdir(exist_ok=True)
    shutil.copyfile(root / 'desktop_app' / 'PACKAGING.md', package / 'desktop_app' / 'PACKAGING.md')
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if python_license.exists():
        shutil.copyfile(python_license, package / '_internal' / 'python-LICENSE.txt')
    print('Built package at', output / 'dist' / 'OracleBot')


if __name__ == '__main__':
    main()
