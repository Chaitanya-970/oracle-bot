# Review findings

The source workflow has been validated across the four courses listed in the count audit. The desktop package has passed offline checks; its live Oracle workflow has not yet been validated. macOS and Linux remain untested.

## Recent fixes

| Bug | What happened | Fix |
| --- | --- | --- |
| Completed quiz reopened | Oracle returned to a completed quiz landing page that still offered Take an Assessment. The bot used that button before checking which sidebar item remained incomplete. | Check completed active assessment status first and move to the next incomplete item. |
| False question-change pause | Oracle removed the APEX RP pagination-reset flag from the URL while the question stayed the same. Comparing the full URLs made the bot think the question changed. | Normalize that flag while retaining checks for real question changes. |
| Replacement key ignored at some desktop pauses | The generic API-error pause waited for Continue and ignored the queued key command. | A verified replacement key can resume an API-related pause. Invalid replacements remain paused. |
| Delay before desktop assessment resume | The worker waited for course/sidebar controls even when an assessment question was already open. | Recognize an assessment question as a valid current state. |
| Fixture failures mixed into live logs | Offline tests intentionally generated failures and questions in the same log files as the real course run. | Use temporary test logs and diagnostics. |
| Stale rate-limit status | The app kept the previous wait message after Groq successfully answered again. | Restore the working status when answers resume. |
| Completion link squeezed out | The expanding log area could consume space before the footer and GitHub link were packed. | Reserve footer space and insert the completion link before the log area. |

Earlier changes also addressed single-choice answer validation, direct navigation past completed lessons, resumable assessment controls, compound API retry delays, session-dialog races, verified assessment results, and feedback lookup independent of question numbering.

## Validation

The source regression suite passed 32 checks after the log audit. Three replacement-key recovery checks passed. The packaged executable's offline self-test checks the window, masked key input, progress, recovery status, completion controls, bundled Chromium, engine helpers, and worker messages.

The final source traversal confirmed all four course lists were processed. This evidence applies to the tested enrolled courses and does not guarantee every Oracle class or desktop platform.

## Workload audit

See [the count audit](course-count-audit.md): **1,455 question slots across 62 assessments**, with attempts counted once. The accidental Database Foundations Quiz 1 loop contributed 380 unnecessary submitted answers, which are excluded.
