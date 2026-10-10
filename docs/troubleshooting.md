# Troubleshooting

## The browser appears to stop

Read the status and latest log. A quota wait, a login prompt, a failed quiz, and completed coursework need different responses. Do not assume every pause needs a new key.

| Message / situation | What to do |
| --- | --- |
| Groq HTTP 429 / API limit | Wait for the displayed retry delay, supply a key with available quota, or use a plan with higher limits. |
| Invalid key / authentication failure | Check the key and its account. Supply a valid key. |
| Network / DNS error | Restore internet access, then Continue or Enter to retry. |
| Oracle sign-in needed | Sign in in the bot's browser, open Classes, then Continue or Enter. |
| Score below 70% | Open Classes and retry; the bot uses recorded feedback where available. |
| Unexpected page | Inspect the browser and diagnostic files before retrying. |
| Profile already in use | Close the other browser using this bot profile, then retry. |
| Finished / completed traversal | Check final Oracle scores and progress; no restart is needed. |

## Groq quota

Limits apply to a Groq organization, so creating another key in that organization does not increase its allowance. Daily limits cover a 24-hour period, while minute limits have shorter waits. Keys do not themselves renew. Follow Groq's reported retry time; there is no fixed renewal time applicable to every key and limit.

Workload, retries, model choice, other account usage, and plan limits determine how much quota is needed. A fixed number of keys cannot guarantee completion.

See [Groq rate limits](https://console.groq.com/docs/rate-limits) and your organization's Limits page for current allowances.

## Replacing a key

In the desktop app, paste the replacement and select **Use key**. A verified replacement resumes an API-related pause automatically.

In the source version, edit .env and save it. Active retries reload the key; a run already at a pause prompt needs Enter afterward. An explicit shell environment key overrides .env.

A key change alone does not require login. Browser restarts and Oracle session expiry can require another sign-in. The bot extends recognized session warnings automatically, but cannot sign in for you after expiry.

## Saved progress and quiz attempts

The bot skips 100% sections and completed sidebar items. Interrupted quizzes can resume through Oracle's Finish Assessment or Resume Assessment control. Saved progress belongs to your Oracle account even if you switch between source and desktop versions.

Retries can draw different questions. The bot retains available Oracle feedback to improve a retry, but AI answers and passing scores are not guaranteed.

## Logs

Source logs: **logs/bot.log**. Diagnostics: **logs/diagnostics/**. Desktop logs: **%LOCALAPPDATA%/OracleBot/logs** on Windows. Offline tests use temporary logs rather than the live files.

When reporting a problem, include the error text and what screen was open. Avoid posting API keys or raw browser-session URLs and diagnostic dumps publicly.
