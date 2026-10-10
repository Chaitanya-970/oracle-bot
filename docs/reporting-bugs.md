# Report a bug

If you find an error or something does not work, please [open a GitHub issue](https://github.com/Chaitanya-970/oracle-bot/issues/new/choose). I’ll investigate the problem and fix it.

You do not need programming experience to report a problem. A clear description of what happened is enough to get started.

## Before opening an issue

Read the app's message and check [troubleshooting](troubleshooting.md). API limits, expired Oracle logins, and a lost internet connection often have an immediate recovery step.

Search [existing issues](https://github.com/Chaitanya-970/oracle-bot/issues) for the same problem. If it has already been reported, add your details to that issue so everything stays together.

## Open the report

1. Sign in to GitHub and open the repository's **Issues** tab.
2. Select **New issue**, then **Bug report** if the form is available.
3. Give the issue a short title, such as **App pauses after replacing the Groq key**.
4. Describe what you did, what you expected, and what happened instead.

Include these details when you know them:

| Detail | Example |
| --- | --- |
| How you ran the bot | Windows desktop ZIP or Python source |
| Operating system | Windows 11, macOS, or Linux distribution |
| Version | ZIP filename and download date, or source commit |
| Course and assessment | Database Foundations, Section 6, Quiz 2 |
| Steps before the problem | Entered replacement key, selected Use key, app stayed paused |
| Error message | The exact message shown in the app or terminal |
| Screenshot or log excerpt | The relevant screen or a few lines around the error |

If you do not know a version or course detail, say **unknown**. Do not delay a useful report just because you cannot fill every field.

## Finding the error details

The desktop window shows progress and errors. Its Windows log is in **%LOCALAPPDATA%/OracleBot/logs/bot.log**. Source logs are in **logs/bot.log** inside the project folder. Both versions keep diagnostic screenshots and reports under their logs directory.

Share only the relevant excerpt. Remove API keys, account identifiers, and signed browser-session URLs from screenshots or logs before posting. Do not upload .env or the browser profile.

## After reporting

I’ll review the issue and may ask for another detail to reproduce it. Updates, workarounds, and the fix will be tracked in the issue. If a new build or source update fixes it, please try it and confirm whether it works for you.
