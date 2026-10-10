# Desktop packaging

This folder is separate from the original command-line bot. Its engine is a
snapshot of that bot. Changes here do not change the running command-line bot.

The desktop window displays progress, warnings, API-limit errors, sign-in
requests, pause instructions, and completion. Each user supplies their own key.
Keys remain in the worker's memory and are not bundled or printed. Desktop
browser profiles, feedback, and diagnostic files use the user's application-data
directory, separate from the original bot's profile.

## Windows preview

Download the Windows ZIP, extract the entire folder, and open OracleBot.exe.
Keep the `_internal` folder beside the executable. Select Start, enter your key,
and select Use key. Sign in through the browser, open Classes, and select
Continue. The progress bar shows the current assessment. Read errors in the
window before selecting Continue after a pause.

If the account hits a daily API limit, the app asks for a key with available
quota. Waiting for quota to recover is also an option. Another key on the same
account shares its quota. Replacing a key in this desktop app keeps the browser
open. If Oracle expires the session or the app restarts, sign in again.

## Build for maintainers

Create a dedicated Python environment and install requirements-build.txt.
Run `python desktop_app/build.py` from the project directory. This downloads
Chromium into the build environment and bundles it with Python, Playwright's
driver, and the application libraries. End users do not run pip, npm, or browser
installation commands.

Build separately on Windows, macOS, and Linux. One executable does not work on
all operating systems. macOS needs its own build and testing, including both
Intel and Apple Silicon if both are distributed. Linux additionally depends on
compatible system libraries required by Chromium; a portable package cannot
guarantee every distribution has those installed. Neither macOS nor Linux has
been validated from this Windows development machine.

The output contains no .env, personal browser profile, or original logs. Before
distribution, run `OracleBot.exe --self-test` and test the graphical workflow.
Validate the live Oracle workflow before distributing a release.
