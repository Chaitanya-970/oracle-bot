# Oracle Bot

**[Download the Windows desktop app](https://github.com/Chaitanya-970/oracle-bot/releases/download/v1.0.0/OracleBot-Windows.zip)** — extract the ZIP and open **OracleBot.exe**. [All releases](https://github.com/Chaitanya-970/oracle-bot/releases).

A helper for Oracle Academy that opens your enrolled courses, saves lesson progress, and answers choice-based quizzes and exams using Groq.

See the [documentation index](docs/README.md) for illustrated setup, platform-specific commands, troubleshooting, review findings, and licensing.

**The four courses below contain 1,455 MCQs across 62 assessments, counting each assessment once.** That is a lot of manual clicking and answering. Depending on your pace, working through it yourself could take days; the bot handles that repetitive work for you. AI answers can still be wrong, so check your final scores in Oracle.

| Course | Quizzes (15 questions each) | Exams (50 questions each) | MCQs |
| --- | ---: | ---: | ---: |
| Database Programming with SQL | 17 | 3 | 405 |
| Database Design | 9 | 3 | 285 |
| Database Foundations | 6 | 3 | 240 |
| Database Programming with PL/SQL | 15 | 6 | 525 |
| **Total** | **47** | **15** | **1,455** |

This is the workload for the four enrolled courses. It includes single-answer, multiple-answer, and True/False choice questions. It excludes reading materials, practice projects, offline tests, repeated quiz attempts, and repeated question extraction after pauses. It counts question slots in one attempt per assessment, not distinct questions in Oracle's full question bank. Other classes can have different content. See [the count audit](docs/course-count-audit.md) for the breakdown.

## Choose how to run it

You can use the Windows desktop ZIP or download the source code. You do not have to clone the repository to use either option.

Both need an internet connection, your Oracle Academy account with enrolled courses, and a Groq API key. Get a key from [Groq Console](https://console.groq.com/keys).

## Option 1: Windows desktop app

Download **[OracleBot-Windows.zip](https://github.com/Chaitanya-970/oracle-bot/releases/download/v1.0.0/OracleBot-Windows.zip)** from GitHub Releases. The source-code ZIP from GitHub’s Code menu is a different download.

1. Right-click the ZIP and select **Extract All**.
2. Open the extracted folder. **OracleBot.exe** is directly inside it.
3. Double-click **OracleBot.exe**. Keep the **_internal** folder beside it.
4. Select **Start**, paste your Groq key in the app, and select **Use key**.
5. Chromium opens. Sign in to Oracle Academy and open **Classes**.
6. Return to the app and select **Continue**.

The ZIP includes Python, Chromium, Playwright, and their application dependencies. Windows users do not need to install Python, Node.js, npm, node modules, or a browser separately. Extract the whole ZIP; copying only the executable will not work.

Progress, API limits, sign-in requests, errors, and completion appear in the app window. The progress bar describes the current assessment, not all four courses. If a Groq account reaches its daily limit, the app asks for a replacement. Paste a key with available quota and select **Use key**; after verification it resumes without another Continue click. An invalid key leaves it paused with an error.

When the run finishes, the window says **Finished. Congratulations!** and offers a link to star [the repository](https://github.com/Chaitanya-970/oracle-bot).

The Windows package has passed offline window, browser, engine, and worker checks. Its complete Oracle workflow has not yet been validated. The source version has been reported working on macOS; follow the Mac setup below. This Windows ZIP will not run directly on macOS or Linux. Linux remains untested, and no native Mac or Linux desktop package is provided.

## Option 2: Source code

### Download and install

1. Open [the repository](https://github.com/Chaitanya-970/oracle-bot), select **Code**, then **Download ZIP**, and extract it. If you already use Git, you can clone it instead.
2. Install a current [Python 3](https://www.python.org/downloads/) and [Google Chrome](https://www.google.com/chrome/). On Windows, enable Python's **Add to PATH** option during installation.
3. Open a terminal in the extracted project folder. On Windows, open that folder in File Explorer, type `powershell` in its address bar, and press Enter.
4. Run this once:

```powershell
python -m pip install -r requirements.txt
```

No Node.js or npm installation is needed.

### Add your key and start

1. Copy **.env.example** to a new file named **.env**. Keep the leading dot and do not add a .txt extension.
2. Open .env in Notepad or another text editor.
3. Replace `your_groq_api_key_here` on the `GROQ_API_KEY=` line with your key, then save.
4. On Windows, double-click **start.bat**.
5. Sign in in the bot's Chrome window and open **Classes**. Press Enter in the terminal when prompted.

You can also start it from the project folder with:

```powershell
python run_bot.py
```

Mac users can follow the steps below. Linux users can follow the [source setup guide](docs/source-setup.md#linux); Linux remains untested.

### Mac setup

The source version has been reported working on a Mac. You do not need a Windows VM or the Windows release ZIP for this setup.

1. Install [Python 3 for macOS](https://www.python.org/downloads/macos/) and [Google Chrome](https://www.google.com/chrome/).
2. Download this repository using **Code > Download ZIP** and extract it, or clone it with Git. Open the folder containing **run_bot.py** and **requirements.txt**.
3. Open **Terminal**. Type `cd ` (including the space), drag the extracted project folder from Finder into Terminal, then press Enter.
4. Run these commands one line at a time to prepare the project:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
nano .env
```

Copy .env.example only on your first setup. If you already have a .env file, keep it and edit it instead.

5. In the editor, replace `your_groq_api_key_here` on the `GROQ_API_KEY=` line with your key from [Groq Console](https://console.groq.com/keys). Keep `BROWSER_CHANNEL=chrome`. Press **Control+O**, then **Enter** to save, and **Control+X** to close the editor.
6. Start the bot:

```bash
python run_bot.py
```

7. Sign in to Oracle Academy in the Chrome window the bot opens, open **Classes**, and press **Enter** in Terminal when prompted. Keep Terminal and the bot's Chrome window open, and keep your Mac awake while it runs.

To run it again, open Terminal in the same project folder and run:

```bash
source .venv/bin/activate
python run_bot.py
```

Mac users do not need Node.js, npm, or a separate Chromium download when using the installed Google Chrome. Use the Terminal commands above; **start.bat** and **OracleBot.exe** are Windows files. If it pauses, follow the Terminal message. Temporary Oracle loading failures retry automatically, and replacing a Groq key works as described below.

The default models are `openai/gpt-oss-120b` for text and `qwen/qwen3.8-27b` for diagrams. You can change them in .env if Groq changes model availability.

## Already completed part of your course?

The bot reads Oracle's saved progress. It skips sections marked 100% complete and moves to unfinished items within partially completed sections. Completed quizzes are skipped. An interrupted assessment can resume through Oracle's Finish Assessment or Resume Assessment control.

Keep using the same account and open Classes when starting a new run. The desktop app and source version have separate browser profiles, but saved course progress belongs to your Oracle account.

## Groq limits: why one free allowance may not be enough

**1,455 MCQs can exceed a single free daily allowance**, especially with long questions, diagrams, or retries. Budget for quota pauses rather than expecting one key to solve everything without a wait.

The number of daily allowances needed depends on workload, model choice, and retries. Creating more keys within the same Groq organization does not add quota: the organization shares its limits.

When limited, you can wait for capacity to recover, switch to a key from an organization with available quota, or use a paid plan with higher limits.

Daily limits cover a 24-hour period; minute limits have shorter waits. API keys themselves do not renew. Groq supplies a retry delay when a request is limited, and some capacity may become available before a whole day has passed. Follow the displayed wait time rather than assuming a universal midnight reset. If your workload needs three daily allowances and you use only one organization, you may need two additional quota-recovery periods; that is an example, not a measured requirement for every user.

For the source version, replace the key in .env and save it. An active API retry reads the new key automatically. If the bot has already paused at a terminal prompt, press Enter to retry after replacing the key. In the desktop app, use the key field and **Use key** button.

Changing a key alone does not require a new Oracle login. **If the browser restarts or Oracle's session expires during the pause, you may need to log in again.** Open Classes afterward and follow the Continue or Enter prompt.


## If it pauses or a quiz fails

Read the message in the app or terminal first.

- **API limit:** wait for quota or provide a replacement key as explained above.
- **Sign-in needed:** sign in in the bot's browser, open Classes, then select Continue or press Enter.
- **Slow Oracle pages:** temporary lesson, answer-selection, and results-loading failures retry automatically up to eight times. The app shows each wait; Continue is only needed if recovery is exhausted.
- **Network error:** restore your connection, then retry.
- **Score below 70%:** the bot records available feedback, returns to the course, and retries only that quiz automatically up to twice when its original lesson link is known. If both retries fail or the link is unavailable, open the failed quiz and select Continue in the app (or press Enter in the terminal). AI answers and passing scores are not guaranteed.
- **Unexpected page:** inspect the browser and diagnostic files before continuing.

Recognized session-extension prompts are handled automatically. If the session has already expired, you must sign in yourself. Completion is checked using Oracle's progress indicators and assessment results.

For the source version, logs are in **logs/** and screenshots and page reports are in **logs/diagnostics/**. The desktop app stores its own logs and browser data under **%LOCALAPPDATA%/OracleBot** on Windows.

Select **Stop** in the app to stop a desktop run. In the source version, use Ctrl+C while running or enter q at a pause prompt. Progress already saved in Oracle remains saved.

## Found an error?

Please [open a GitHub issue](https://github.com/Chaitanya-970/oracle-bot/issues/new/choose). I’ll investigate and fix it. You do not need coding experience: explain what happened and include the error message if possible. The [bug-reporting guide](docs/reporting-bugs.md) explains what details to include.

## Development and testing

The supported source entry points are **start.bat** and **run_bot.py**. The desktop code is a separate snapshot in **desktop_app/**. See [packaging notes](desktop_app/PACKAGING.md) for building it.

With Chrome installed, run the offline checks from the project folder:

```powershell
python -m unittest discover -s tests -v
```

The tests use separate temporary logs. Passing offline checks does not prove compatibility with every Oracle class.

If this helped, please star [Oracle Bot on GitHub](https://github.com/Chaitanya-970/oracle-bot).

## License

Project code is licensed under the [Apache License 2.0](LICENSE). See [NOTICE](NOTICE) and [licensing details](docs/licensing.md). Bundled dependencies retain their own licenses.
