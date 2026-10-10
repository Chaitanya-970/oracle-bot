# Oracle Academy Auto-Course Bot

An automated helper for Oracle Academy courses. It automatically:
- Clicks **Save and Continue** on reading slides and lessons.
- Detects quizzes, reads questions, and answers them automatically using **Groq AI**.
- Handles all 4 courses on your dashboard without manual clicking.

---

## Quick Setup (Under 2 Minutes)

You don't need programming knowledge. Follow these 4 simple steps:

### 1. Get a Free Groq API Key
1. Go to https://console.groq.com/keys.
2. Sign in with Google or GitHub (it is free).
3. Click **"Create API Key"**, copy your key (it starts with `gsk_...`).

### 2. Paste Your Key
1. In this folder, open the file named **`.env`** (right-click -> *Open with* -> *Notepad*).
2. Find this line:
   ```env
   GROQ_API_KEY=your_groq_api_key_here
   ```
3. Replace `your_groq_api_key_here` with the key you copied in step 1.
4. Save the file (`Ctrl + S`) and close Notepad.

### 3. Install Dependencies and Start the Bot
- Install Python and Google Chrome, then run `python -m pip install -r requirements.txt` once from this folder.
- Simply double-click **`start.bat`**.

### 4. Log in
1. A Google Chrome window will pop up automatically.
2. Sign in to your Oracle Academy account inside that Chrome window.
3. Once you see your **Classes** or course page on screen, go back to the terminal window and **press Enter**.
4. The bot will click through the lessons and solve the quizzes.

Oracle may require a fresh sign-in when Chrome restarts. The persistent profile stores browser data, but Oracle controls the lifetime of its login session.

The bot verifies the API key and model availability before opening Chrome. Current defaults are `openai/gpt-oss-120b` for text and `qwen/qwen3.8-27b` for diagrams. Both can be changed in `.env`.

Session-extension warnings are checked between actions and during AI requests. The bot clicks the extension button in a session warning automatically. If the session already expired, it pauses for you to sign in and open Classes or the course outline before retrying.

Course completion is confirmed through Oracle's sidebar indicators and assessment results; the bot stops on an unrecognized state rather than claiming completion.

---

## What If It Pauses?

If the bot encounters an unusual page or needs your input:
1. It will pause and show a message on your screen.
2. It automatically saves a picture of what went wrong in the **`logs/diagnostics`** folder.
3. Look at your Chrome browser, fix the state, open Classes or the course outline, and press **Enter** in the terminal to retry. Enter `q` to stop.

---

## Folder Overview

- **`start.bat`**: Double-click this to run the bot.
- **`.env`**: Where you paste your Groq API key.
- **`logs/`**: Keeps a history of everything the bot did.
- **`logs/diagnostics/`**: If an unexpected screen happens, photos and reports are saved here.
- **`browser_profile/`**: Stores browser data; Oracle may still require another sign-in.
- **`review_live.py`**: Review harness that reloads code fixes while keeping Chrome open.
- **`tests/`**: Offline regressions. Run `python -m unittest discover -s tests -v` (requires Chrome).
- **`prototypes/`**: Early experimental scripts.

Use `run_bot.py` or `start.bat` as the supported entry point.
