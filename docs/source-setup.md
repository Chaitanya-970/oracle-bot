# Running from source

The source version needs Python 3, Google Chrome, internet, enrolled Oracle courses, and a Groq key. No Node.js or npm installation is needed.

Download the repository using **Code > Download ZIP** and extract it, or clone it if you already use Git. Run commands from the folder containing **run_bot.py** and **requirements.txt**.

## Windows

Install Python with **Add to PATH** enabled and install Google Chrome. Open PowerShell in the project folder:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Open .env in Notepad, replace the placeholder on the GROQ_API_KEY line, and save. Then run:

```powershell
.venv\Scripts\python.exe run_bot.py
```

Alternatively, install requirements into your regular Python with `python -m pip install -r requirements.txt`, then double-click **start.bat**. start.bat uses the Python on PATH; it does not automatically select the virtual environment above.

Sign in in Chrome, open Classes, and press Enter in the terminal when asked.

## macOS

The source version has been reported working on macOS. Use the Python source directly; a Windows VM is not required. The Windows ZIP is not compatible with macOS. See the [Mac walkthrough in the README](../README.md#mac-setup) for instructions including opening Terminal and editing your key.

Install Python 3 and Google Chrome, then open Terminal in the project folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Edit .env in a text editor and enter your key. Start the bot:

```bash
python run_bot.py
```

Sign in in Chrome, open Classes, and press Enter in Terminal. Do not use start.bat on macOS.

## Linux

This platform also needs a live test. Use a graphical desktop, Python 3 with venv support, and Google Chrome:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Edit .env, then run `python run_bot.py`. Some distributions need additional browser system libraries. See [Playwright installation](https://playwright.dev/python/docs/intro) for current platform requirements.

## Configuration and recovery

The default browser channel is `chrome`; install Google Chrome rather than assuming Playwright's Chromium download will satisfy that channel. The current text and diagram models can be changed in .env.

Changing GROQ_API_KEY in .env takes effect on the next active API retry. If the bot has already stopped at a pause prompt, press Enter after replacing it. An explicitly supplied shell environment key takes precedence over .env.

See [troubleshooting](troubleshooting.md) for quota limits, login, and interrupted assessments.
