# Changes after the security audit (3 Nov 2026)

Each line maps an issue number from `Orca_Smart_Router_Audit.pdf` to what changed.

## Security & privacy

| # | Issue | Fix |
|---|---|---|
| 1 | PowerShell injection in notifications | Toast title and message are passed as environment variables to a fixed script, never pasted into the script text (`send_windows_notification`, `run_powershell`). |
| 2 | Auto-start runs whatever is in the (possibly synced) folder | The installer copies the script to `%LOCALAPPDATA%\OrcaSmartRouter\`, and the Startup shortcut runs that local copy. Edits in the shared folder no longer run at login. It warns when the source folder looks cloud-synced and prints the SHA-256 of what it installed. |
| 3 | Prompts sent to another AI company without asking | The guardian shows a Yes/No dialog that names the provider before switching. `--allow` limits which providers it may switch to. `--auto` is opt-in. |
| 4 | `-ExecutionPolicy Bypass` + hidden VBS launcher | Both removed. `silent_guardian.vbs` is gone: the shortcut starts `pythonw.exe` directly, which has no window anyway. |
| 5 | `pythonw` / `orca` found via PATH and current folder | `pythonw.exe` is resolved once at install time from the running Python and stored as a full path. `orca.exe` is looked up only in absolute PATH entries (never the current folder), only as a real `.exe` (a `.cmd` shim would let cmd.exe re-parse prompt text), or set via `ORCA_CLI_PATH`. PowerShell is called by full path. The `.bat` files set `NoDefaultCurrentDirectoryInExePath=1`. |
| 6 | Installer broke on a `'` in the folder path | The installer logic moved into Python. Paths reach PowerShell only as environment variables. |
| 7 | Prompts written to the log in plain text | The launch command is logged with the prompt replaced by `<N chars, not logged>`. The log moved to the local data folder. |
| 8 | Shipped log and `.pyc` leak the author's username and path | They're not included in the fixed folder. Delete `failover_history.log` and `__pycache__\` from the shared Drive folder too. |

## Bugs

| # | Issue | Fix |
|---|---|---|
| 9 | Cooldown only applied to check 1, so several agents launched at once | One global cooldown (`--cooldown`, default 600 s) and at most one switch per cycle, for every trigger. |
| 10 | Failover fired when any provider ran out, even an unused one | Quota exhaustion on its own now only sends one notification (and logs recovery). A switch needs an actual failed agent. |
| 11 | Handoff prompt didn't include the task | The handoff includes the original task (truncated at 8,000 chars) and tells the agent to check `git status` / `git diff` and continue rather than restart. If the task can't be recovered, it tells the agent to summarise the changes and ask before touching anything. |
| 12 | Backup launched in whichever worktree was focused | The backup always launches in the failed agent's own worktree, and only takes focus when you clicked Yes. |
| 13 | Any agent error triggered a switch | Hook errors only trigger a switch when the error text is a rate-limit or quota message (whole-word match). Worktree failures need the provider to actually be exhausted. |
| 14 | Stale errors triggered switches at boot; a pane's later failures were ignored | Failures present when the guardian starts are ignored. Failures are tracked by a signature that's forgotten once the failure clears, so the same pane failing again later is handled again. |
| 15 | "100% free / Healthy" shown when Orca was unreachable | Missing data is shown as "Unknown" with a banner. `status` exits with code 2. `best --launch` refuses to launch when quota is unknown or every model is exhausted. The guardian pauses (and logs once) while Orca is unreachable. |
| 16 | Uninstaller killed every `pythonw.exe` | It stops only processes whose command line is `orca_model_router.py guard`. |
| 17 | Two guardians could run at once | An exclusive lock file in the data folder. A second guardian exits with a message. |
| 18 | Keywords matched inside other words | Whole-word matching (plurals allowed): "uploads" no longer matches "ads", and "research" no longer matches "search". |
| 19 | `null` values in Orca's JSON crashed it | Every field read goes through type-checked helpers (`_as_dict`, `_as_list`, `_as_percent`). |
| 20 | Failed provider might not be excluded from backups | Orca names like `claude-code` are normalized to catalog keys. If the provider still can't be identified, it doesn't switch at all. |
| 21 | Always exited 0; `.bat` showed ✅ on failure | `main()` returns real exit codes. `3_Switch` checks `errorlevel` and rejects invalid menu choices. |
| 22 | A `"` in the task broke `2_Recommend` | Python now asks for the task and the Y/N itself, so any characters are safe. It also launches the same recommendation it showed instead of re-computing it. |
| 23 | Log grew forever | Rotated to `.1` at 1 MB. "Orca not reachable" and repeated loop errors are logged once, not every 15 s. |

## Code quality & docs

| # | Issue | Fix |
|---|---|---|
| 24 | Failover logic copy-pasted four times | Now `find_failovers`, `pick_backup`, `perform_failover` and `build_handoff_prompt`, each written once. The dead duplicate block is gone. |
| 25 | Unused names, misleading comments | `STATUS_CACHE_FILE` and the unused progress bar removed. Comments corrected. |
| 26 | `--threshold` ignored in places | Dashboard, recommender and guardian all use the same threshold. `status` and `best` accept `--threshold` too. |
| 27 | Hardcoded Python 3.12 path | Gone with the VBS. `pythonw.exe` comes from whichever Python runs the installer. |
| 28 | README said Task Scheduler; % table was a stale snapshot | README rewritten: explains the Startup-folder shortcut, the local copy, every option, and where logs live. Static % numbers removed. |

## Also fixed while rewriting (not in the audit)

- `echo` and `title` lines contained an unescaped `&`, which cmd treats as "run another command". Menu lines were cut off and errors like `'API)' is not recognized` appeared. They're escaped as `^&` now.
- Under `pythonw`, every `orca` / PowerShell call could flash a console window. Calls now use `CREATE_NO_WINDOW`.
- `5_` / `6_` were renamed to `5_Enable_Guardian_Auto_Start.bat` / `6_Disable_Guardian_Auto_Start.bat`, since they never used Task Scheduler.

## Second pass: independent code review

| Problem found in the first rewrite | Fix |
|---|---|
| A handled failure could fire again when the backup agent went idle, a quota reading was missing, or one poll came back empty, so backups repeated. | Handled failures are tracked against every failed pane Orca reports, before the "exhausted" and "busy" filters, and are only forgotten after missing for 3 polls in a row. Panes are also remembered by when they were handled, because Orca writes the hook file a few seconds after `worktree ps` shows the failure. |
| `switch` and `best --launch` from the `.bat` files couldn't find a worktree: Orca resolves "current worktree" from the folder you run in, and the `.bat` runs in this tool's folder. | New `--worktree` option. Without it, the worktree you're in is used, and otherwise a numbered pick list of your Orca worktrees appears. |
| Worktree ids were passed bare. | They're passed as `id:<worktreeId>`, the form Orca's own runtime uses, so a value can't be read as another flag. |
| An exception mid-failover skipped the bookkeeping, so it retried every poll. | The bookkeeping and cooldown run in `finally`. NUL characters in arguments and unencodable text in the log are handled. |
| A hook error alone could trigger a switch (even "429" from a provider with quota left). | Hook failures need the provider to be exhausted too, and "busy" is checked per worktree. `rate_limit_error` / `quota_exceeded` style text is matched. Only entries received after the guardian started count. |
| A provider with reset credits but no quota could be picked as a backup. | Backups must be HEALTHY or WARNING. |
| "No backup available" was permanent. | It's retried every poll and notified once, and a launch happens when quota frees up. After you click Yes, quota is re-checked before launching. |
| Smaller: a launch timeout could double-launch; Ctrl+C could print a traceback; the hook file with a BOM was unreadable; PowerShell stderr could corrupt the stopped-process count; install continued when it couldn't stop an old guardian; toasts from an unregistered app id may not show. | Launch timeout raised to 60 s and counted for cooldown. Ctrl+C is caught anywhere. The file is read as `utf-8-sig`, with the last good copy kept. Only stdout is parsed. Install aborts. Toasts use PowerShell's registered app id. |

## Verified

- An offline test harness (fake Orca data) ran the logic under Python 3.13, with a grammar check against Python 3.8. All 41 checks passed. They cover quota parsing, keyword matching, selectors, handoff prompts, and guardian scenarios: stale failures, repeats, cooldown, decline, no backup, exceptions, Orca down, and hook entries.
- Read-only commands (`status`, `best`, `--help`) were run against a real Orca install. Every field name the script reads (`rateLimits`, `worktreeId`, `displayName`, `agents[].paneKey/state/agentType/prompt`, `mainAgent.outcome`) was confirmed in real Orca output and in Orca's CLI source.

## Not verified

- No agent was actually launched or failed over, and `install-autostart` / `uninstall-autostart` haven't been run. Try `4_Run_Auto_Failover_Guardian.bat` in a console first, then enable auto-start.
- No real `last-status.json` failure entry was available to check, so its fields (`hookEventName`, `payload.error`, `payload.agentType`) still follow the original script's assumptions. `receivedAt` and `worktreeId` were confirmed in Orca's source.
