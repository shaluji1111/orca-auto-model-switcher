"""
Orca Smart Model Switcher & Auto-Failover Guardian
==================================================
Multi-model quota monitoring, task-based model selection, and automatic failover
for Claude, Codex (GPT-6), Antigravity (Gemini), and Grok inside Orca IDE.
"""

import sys
import os
import re
import json
import time
import shutil
import hashlib
import subprocess
import argparse
from datetime import datetime
from typing import Dict, Any, List, Optional, Set, Tuple

# Ensure Windows terminal can print UTF-8 emojis without crashing, and pythonw doesn't crash on print
if sys.platform == "win32":
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    else:
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        except Exception:
            pass

    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    else:
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
        except Exception:
            pass

# Base paths. The log, the lock file and the auto-start copy live in a local per-user folder
# that is never synced, whichever folder this script is run from.
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "OrcaSmartRouter")
FAILOVER_LOG_FILE = os.path.join(DATA_DIR, "failover_history.log")
GUARDIAN_LOCK_FILE = os.path.join(DATA_DIR, "guardian.lock")
ORCA_LAST_STATUS_FILE = (
    os.path.join(os.environ["APPDATA"], "orca", "agent-hooks", "last-status.json")
    if os.environ.get("APPDATA") else None
)

# Tuning
DEFAULT_THRESHOLD = 95            # session % used at which a provider counts as exhausted
WEEKLY_EXHAUSTED_PERCENT = 98     # weekly % used at which a provider counts as exhausted
WARNING_MARGIN = 15               # show WARNING this many points before exhaustion
MIN_BACKUP_FREE_PERCENT = 20      # a backup provider needs more than this much quota left
DEFAULT_COOLDOWN_SECONDS = 600    # at most one failover launch per cooldown window
FORGET_AFTER_POLLS = 3            # a handled failure is forgotten after missing from this many polls
MAX_HANDOFF_PROMPT_CHARS = 8000   # keeps the orca command line well under the Windows limit
MAX_LOG_BYTES = 1_000_000         # the log is rotated to .1 beyond this size
LAUNCH_TIMEOUT_SECONDS = 60

# Windows auto-start
STARTUP_SHORTCUT_NAME = "Orca Smart Router Guardian.lnk"
OLD_SHORTCUT_NAMES = ["Orca_Auto_Failover_Guardian.lnk"]  # created by the original installer
SYNCED_FOLDER_MARKERS = ("onedrive", "google drive", "googledrive", "my drive", "dropbox", "icloud", "box sync")

# Selector prefixes Orca understands for --worktree; raw ids get "id:" like Orca's own runtime uses
WORKTREE_SELECTOR_PREFIXES = ("id:", "name:", "path:", "branch:", "issue:", "identity:", "folder:")

# Don't flash a console window for every orca/powershell call when running under pythonw
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Model Catalog & Task Profiles
MODEL_CATALOG = {
    "claude": {
        "name": "Anthropic Claude",
        "default_model": "sonnet",
        "models": {
            "sonnet": {
                "id": "claude-sonnet-5-5",
                "label": "Claude Sonnet 5.5",
                "strengths": ["Fullstack Coding", "Refactoring", "Clean Architecture", "Fast Implementations"],
                "best_for": ["code", "refactor", "bug", "feature", "frontend", "backend", "typescript", "python"],
                "speed": "Fast",
                "reasoning": "High"
            },
            "opus": {
                "id": "claude-opus-5-5",
                "label": "Claude Opus 5.5",
                "strengths": ["Deep Reasoning", "Complex System Architecture", "Multi-file Planning", "Writing"],
                "best_for": ["architect", "system design", "complex planning", "strategy", "algorithm", "hard problem"],
                "speed": "Moderate",
                "reasoning": "Maximum"
            },
            "haiku": {
                "id": "claude-haiku-5-5",
                "label": "Claude Haiku 5.5",
                "strengths": ["Ultra-fast Responses", "Lightweight Scripts", "Regex & Data Formatting"],
                "best_for": ["quick", "simple", "fast", "format", "rename", "convert", "regex"],
                "speed": "Ultra-Fast",
                "reasoning": "Standard"
            }
        }
    },
    "codex": {
        "name": "OpenAI Codex",
        "default_model": "gpt-6.1-sol",
        "models": {
            "gpt-6.1-sol": {
                "id": "gpt-6.1-sol",
                "label": "GPT-6.1 Sol",
                "strengths": ["Workhorse Coding", "API Integration", "Debugging", "Database Queries"],
                "best_for": ["code", "backend", "api", "database", "sql", "debug", "integration", "automation"],
                "speed": "Fast",
                "reasoning": "High"
            },
            "gpt-6-astra": {
                "id": "gpt-6-astra",
                "label": "GPT-6 Astra",
                "strengths": ["Frontier Intelligence", "Complex Logic", "Deep Math & Research", "Challenging Architecture"],
                "best_for": ["architect", "advanced logic", "math", "hardest problems", "deep reasoning"],
                "speed": "Moderate",
                "reasoning": "Maximum"
            },
            "gpt-6-luna": {
                "id": "gpt-6-luna",
                "label": "GPT-6 Luna",
                "strengths": ["Affordable & Fast", "Quick Scripts", "Text Processing"],
                "best_for": ["quick", "lightweight", "script", "summary", "text"],
                "speed": "Ultra-Fast",
                "reasoning": "Standard"
            }
        }
    },
    "antigravity": {
        "name": "Google Antigravity (Gemini)",
        "default_model": "gemini-3.8-flash",
        "models": {
            "gemini-3.8-flash": {
                "id": "gemini-3.8-flash",
                "label": "Gemini 3.8 Flash (High)",
                "strengths": ["Massive 1M+ Context", "Entire Codebase Audit", "File Search", "Speed"],
                "best_for": ["large context", "repo", "repository", "audit", "codebase", "entire", "search files", "multi-doc", "long doc"],
                "speed": "Ultra-Fast",
                "reasoning": "High"
            },
            "gemini-3.8-pro": {
                "id": "gemini-3.8-pro",
                "label": "Gemini 3.8 Pro",
                "strengths": ["Deep Multi-step Reasoning", "Complex Tool Execution", "Multimodal Analysis"],
                "best_for": ["deep analysis", "complex research", "multimodal", "image analysis"],
                "speed": "Moderate",
                "reasoning": "Maximum"
            }
        }
    },
    "grok": {
        "name": "SpaceXAI Grok",
        "default_model": "grok-4.7",
        "models": {
            "grok-4.7": {
                "id": "grok-4.7",
                "label": "Grok 4.7",
                "strengths": ["Real-time Web Search", "Market Intelligence", "Trend Analysis", "Unfiltered Reasoning"],
                "best_for": ["search", "web", "market", "trends", "news", "competitor analysis", "social media", "ads"],
                "speed": "Fast",
                "reasoning": "High"
            }
        }
    }
}

# Which usage window drives each provider's status (Grok only reports a weekly window)
PRIMARY_WINDOW = {"claude": "session", "codex": "session", "antigravity": "session", "grok": "weekly"}

# Orca reports agent types like "claude" or "codex"; map these and close variants onto catalog keys
PROVIDER_ALIASES = {
    "claude": ("claude", "anthropic"),
    "codex": ("codex", "openai", "gpt"),
    "antigravity": ("antigravity", "gemini", "google"),
    "grok": ("grok", "xai"),
}

# Error text that means "out of quota / rate limited". Matched as whole words after "_" becomes a
# space, so "rate_limit_error" matches but "1429 lines" doesn't match "429".
RATE_LIMIT_PATTERNS = [
    re.compile(r"\b" + re.escape(keyword) + r"\b")
    for keyword in ("rate limit", "usage limit", "5-hour limit", "token limit",
                    "quota", "too many requests", "429")
]

# PowerShell's own app id: Windows only shows toasts for registered app ids
TOAST_SCRIPT = "; ".join([
    "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null",
    "$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)",
    "$textNodes = $template.GetElementsByTagName('text')",
    "$textNodes.Item(0).AppendChild($template.CreateTextNode($env:ORCA_TOAST_TITLE)) > $null",
    "$textNodes.Item(1).AppendChild($template.CreateTextNode($env:ORCA_TOAST_MESSAGE)) > $null",
    "$toast = [Windows.UI.Notifications.ToastNotification]::new($template)",
    r"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe').Show($toast)",
])

CREATE_SHORTCUT_SCRIPT = "; ".join([
    "$ErrorActionPreference = 'Stop'",
    "$ProgressPreference = 'SilentlyContinue'",
    "$startup = [Environment]::GetFolderPath('Startup')",
    r"foreach ($old in ($env:ORCA_OLD_LNK_NAMES -split '\|')) { if ($old) { $path = Join-Path $startup $old; if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force } } }",
    "$lnk = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $startup $env:ORCA_LNK_NAME))",
    "$lnk.TargetPath = $env:ORCA_TARGET",
    "$lnk.Arguments = $env:ORCA_ARGS",
    "$lnk.WorkingDirectory = $env:ORCA_WORKDIR",
    "$lnk.Description = 'Orca Smart Router - auto-failover guardian'",
    "$lnk.Save()",
])

REMOVE_SHORTCUTS_SCRIPT = "; ".join([
    "$ErrorActionPreference = 'Stop'",
    "$ProgressPreference = 'SilentlyContinue'",
    "$startup = [Environment]::GetFolderPath('Startup')",
    "$removed = 0",
    r"foreach ($name in ($env:ORCA_LNK_NAMES -split '\|')) { if ($name) { $path = Join-Path $startup $name; if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force; $removed++ } } }",
    "Write-Output $removed",
])

# Matches only guardian processes: "...orca_model_router.py guard" or "...orca_model_router.py\" guard"
STOP_GUARDIANS_SCRIPT = "; ".join([
    "$ErrorActionPreference = 'Stop'",
    "$ProgressPreference = 'SilentlyContinue'",
    r"$procs = @(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^pythonw?[0-9.]*\.exe$' -and $_.CommandLine -match 'orca_model_router\.py.? guard' })",
    "foreach ($p in $procs) { Stop-Process -Id $p.ProcessId -Force }",
    "Write-Output $procs.Count",
])


class OrcaUnavailable(Exception):
    """The Orca CLI couldn't be found, failed, or returned unreadable output."""


class OrcaTimeout(OrcaUnavailable):
    """The Orca CLI didn't answer in time; the command may still have taken effect."""


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _as_percent(value: Any) -> Optional[float]:
    """Return a 0-100 number, or None when Orca sent null, a string, or nothing."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(0.0, min(100.0, float(value)))


def _fmt_pct(value: Optional[float]) -> str:
    return "?" if value is None else f"{value:.0f}%"


def log_event(message: str) -> None:
    message = " ".join(str(message).splitlines())  # one line per event, even if a name contains newlines
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        print(f"ℹ️  {message}")
    except (OSError, UnicodeError):
        pass
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        if os.path.exists(FAILOVER_LOG_FILE) and os.path.getsize(FAILOVER_LOG_FILE) > MAX_LOG_BYTES:
            os.replace(FAILOVER_LOG_FILE, FAILOVER_LOG_FILE + ".1")
        with open(FAILOVER_LOG_FILE, "a", encoding="utf-8", errors="backslashreplace") as f:
            f.write(f"[{timestamp}] {message}\n")
    except OSError:
        pass


def find_on_path(name: str) -> Optional[str]:
    """Find an executable on PATH, skipping relative entries so the current folder is never searched.

    On Windows only real .exe files are accepted: running a .cmd/.bat shim with arguments
    lets cmd.exe re-parse them, which would let prompt text inject commands.
    """
    filename = name + ".exe" if sys.platform == "win32" else name
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        entry = entry.strip().strip('"')
        if not entry or not os.path.isabs(entry):
            continue
        candidate = os.path.join(entry, filename)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def orca_executable() -> Optional[str]:
    override = os.environ.get("ORCA_CLI_PATH")
    if override:
        is_exe = sys.platform != "win32" or override.lower().endswith(".exe")
        return override if is_exe and os.path.isabs(override) and os.path.isfile(override) else None
    return find_on_path("orca")


def powershell_executable() -> str:
    return os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")


def run_orca(args: List[str], timeout: int) -> Dict[str, Any]:
    """Run an `orca ... --json` command and return its parsed output. Raises OrcaUnavailable."""
    exe = orca_executable()
    if not exe:
        raise OrcaUnavailable("orca.exe not found on PATH (set ORCA_CLI_PATH to its full path)")
    try:
        proc = subprocess.run(
            [exe, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=_NO_WINDOW
        )
    except subprocess.TimeoutExpired as e:
        raise OrcaTimeout(f"'orca {' '.join(args[:2])}' didn't answer within {timeout}s") from e
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        # ValueError: an argument contained a NUL character
        raise OrcaUnavailable(f"could not run orca: {e}") from e
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:300]
        raise OrcaUnavailable(f"'orca {' '.join(args[:2])}' failed: {detail or 'exit code ' + str(proc.returncode)}")
    try:
        return _as_dict(json.loads(proc.stdout))
    except ValueError as e:
        raise OrcaUnavailable(f"orca returned invalid JSON: {e}") from e


def run_powershell(script: str, variables: Dict[str, str], timeout: int = 60) -> Tuple[bool, str, str]:
    """Run a fixed PowerShell script. Values go in as environment variables, never into the script text.

    Returns (ok, stdout, stderr)."""
    try:
        proc = subprocess.run(
            [powershell_executable(), "-NoProfile", "-NonInteractive", "-Command", script],
            env=dict(os.environ, **variables),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=_NO_WINDOW
        )
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        return False, "", str(e)
    return proc.returncode == 0, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def get_live_orca_limits() -> Dict[str, Any]:
    """Fetch live token rate limits from the Orca runtime CLI. Raises OrcaUnavailable."""
    data = run_orca(["account", "list", "--json"], timeout=10)
    return _as_dict(_as_dict(data.get("result")).get("rateLimits"))


def format_countdown(resets_at_ms: Any) -> str:
    """Format millisecond epoch to countdown like '2h 15m' or 'Ready'."""
    if isinstance(resets_at_ms, bool) or not isinstance(resets_at_ms, (int, float)) or not resets_at_ms:
        return "N/A"
    now_ms = int(time.time() * 1000)
    diff_sec = int(resets_at_ms - now_ms) // 1000
    if diff_sec <= 0:
        return "Ready to Reset"
    hours = diff_sec // 3600
    minutes = (diff_sec % 3600) // 60
    if hours > 24:
        days = hours // 24
        return f"{days}d {hours % 24}h"
    return f"{hours}h {minutes}m"


def is_exhausted(info: Dict[str, Any]) -> bool:
    return info.get("status") in ("EXHAUSTED", "CREDIT_READY")


def assess_provider_health(limits: Dict[str, Any], threshold: int = DEFAULT_THRESHOLD) -> Dict[str, Any]:
    """Parse raw Orca limits into health metrics. Providers Orca doesn't report are UNKNOWN, never 'free'."""
    health_report = {}
    weekly_limit = max(threshold, WEEKLY_EXHAUSTED_PERCENT)

    for key, window in PRIMARY_WINDOW.items():
        data = _as_dict(limits.get(key))
        primary = _as_dict(data.get(window))
        weekly = _as_dict(data.get("weekly"))
        used = _as_percent(primary.get("usedPercent"))
        weekly_used = _as_percent(weekly.get("usedPercent"))
        credits = _as_dict(data.get("rateLimitResetCredits")).get("availableCount")
        credits = credits if isinstance(credits, int) and not isinstance(credits, bool) else 0

        if used is None:
            status = "UNKNOWN"
        elif used >= threshold or (weekly_used or 0) >= weekly_limit:
            status = "CREDIT_READY" if credits > 0 else "EXHAUSTED"
        elif used >= threshold - WARNING_MARGIN or (weekly_used or 0) >= weekly_limit - WARNING_MARGIN:
            status = "WARNING"
        else:
            status = "HEALTHY"

        health_report[key] = {
            "name": MODEL_CATALOG[key]["name"],
            "session_used": used,
            "session_free": None if used is None else 100 - used,
            "weekly_used": weekly_used,
            "resets_in": format_countdown(primary.get("resetsAt")),
            "reset_credits": credits,
            "status": status,
            "is_available": status not in ("EXHAUSTED", "UNKNOWN")
        }

    return health_report


def fetch_health(threshold: int) -> Tuple[Dict[str, Any], Optional[str]]:
    """Return (health, error). On error every provider is UNKNOWN."""
    try:
        return assess_provider_health(get_live_orca_limits(), threshold), None
    except OrcaUnavailable as e:
        return assess_provider_health({}, threshold), str(e)


def print_status_dashboard(health: Dict[str, Any], orca_error: Optional[str] = None) -> None:
    """Print an eye-catching CLI status dashboard."""
    print("\n" + "=" * 78)
    print(" 🚀 ORCA LIVE MODEL & TOKEN HEALTH MONITOR")
    print("=" * 78)
    if orca_error:
        print(f" ⚠️  Orca se live data nahi mila: {orca_error}")
        print("    Neeche ke numbers 'Unknown' hain, free nahi.")
        print("-" * 78)
    print(f" {'PROVIDER':<28} | {'FREE':>6} | {'USED':>6} | {'STATUS':<16} | {'RESETS IN'}")
    print("-" * 78)

    status_icons = {
        "HEALTHY": "🟢 Healthy",
        "CREDIT_READY": "🟢 Credits Avail",
        "WARNING": "🟡 Warning",
        "EXHAUSTED": "🔴 Exhausted",
        "UNKNOWN": "⚪ Unknown"
    }

    for info in health.values():
        badge = status_icons.get(info["status"], info["status"])
        extra = f" (⚡{info['reset_credits']} credits)" if info.get("reset_credits", 0) > 0 else ""
        print(f" {info['name']:<28} | {_fmt_pct(info['session_free']):>6} | {_fmt_pct(info['session_used']):>6} | {badge:<16} | {info['resets_in']}{extra}")

    print("=" * 78)
    print(" 💡 TIP: Jab kisi model me tokens khatam hote hain, Orca Guardian aapse")
    print("    pooch kar doosre best healthy model par switch kar deta hai.")
    print("=" * 78 + "\n")


_KEYWORD_PATTERNS: Dict[str, Any] = {}


def _keyword_matches(keyword: str, text: str) -> bool:
    """Whole-word match (plurals allowed), so 'ads' doesn't match 'uploads' or 'search' match 'research'."""
    pattern = _KEYWORD_PATTERNS.get(keyword)
    if pattern is None:
        pattern = re.compile(r"\b" + re.escape(keyword) + r"(?:s|es)?\b")
        _KEYWORD_PATTERNS[keyword] = pattern
    return bool(pattern.search(text))


def recommend_best_model_for_task(task_prompt: str, health: Dict[str, Any]) -> Dict[str, Any]:
    """Score all available models against the task prompt and live token health."""
    task_lower = task_prompt.lower()
    any_quota_known = any(info.get("status") != "UNKNOWN" for info in health.values())

    scored_models = []

    for agent_key, agent_data in MODEL_CATALOG.items():
        provider_health = health.get(agent_key, {})
        status = provider_health.get("status", "UNKNOWN")
        free_percent = provider_health.get("session_free")
        quota_known = status != "UNKNOWN"

        if not quota_known:
            # No quota data: rank on suitability alone when nothing is known, else behind known providers
            token_multiplier = 0.1 if any_quota_known else 0.5
        elif not provider_health.get("is_available"):
            token_multiplier = 0.0  # Disqualify exhausted models
        else:
            token_multiplier = max(0.05, free_percent / 100.0)

        for model_slug, model_meta in agent_data["models"].items():
            # Calculate match score based on keywords
            match_score = 40  # baseline suitability
            matched_keywords = [kw for kw in model_meta["best_for"] if _keyword_matches(kw, task_lower)]
            match_score += 25 * len(matched_keywords)

            # Cap base suitability at 100
            suitability = min(100, match_score)

            # Final Score considers both task suitability & available tokens
            final_score = suitability * token_multiplier

            scored_models.append({
                "agent": agent_key,
                "model_key": model_slug,
                "model_id": model_meta["id"],
                "label": model_meta["label"],
                "provider_name": agent_data["name"],
                "suitability": suitability,
                "free_tokens": free_percent,
                "quota_known": quota_known,
                "final_score": round(final_score, 1),
                "strengths": model_meta["strengths"],
                "matched_keywords": matched_keywords,
                "is_available": provider_health.get("is_available", False)
            })

    # Sort by final score descending
    scored_models.sort(key=lambda x: x["final_score"], reverse=True)

    return {
        "recommended": scored_models[0],
        "fallback": scored_models[1] if len(scored_models) > 1 else None,
        "all_ranked": scored_models
    }


def print_recommendation(task: str, rec: Dict[str, Any], orca_error: Optional[str]) -> None:
    top = rec["recommended"]
    fallback = rec["fallback"]

    print("\n" + "=" * 70)
    print(" 🎯 ORCA SMART MODEL RECOMMENDATION")
    print("=" * 70)
    print(f" 📝 Task: \"{task}\"")
    if orca_error:
        print(f" ⚠️  Live quota nahi mila ({orca_error}). Sirf task ke hisaab se ranking hai.")
    print("-" * 70)
    print(f" 🥇 RECOMMENDED BEST MODEL: {top['label']} ({top['provider_name']})")
    print(f"    • Token Headroom : {_fmt_pct(top['free_tokens'])} Free Available")
    print(f"    • Match Score    : {top['final_score']} / 100")
    print(f"    • Key Strengths  : {', '.join(top['strengths'])}")
    if top['matched_keywords']:
        print(f"    • Matched Needs  : {', '.join(top['matched_keywords'])}")

    if fallback:
        print("-" * 70)
        print(f" 🥈 BACKUP RUNNER-UP     : {fallback['label']} ({fallback['provider_name']})")
        print(f"    • Token Headroom : {_fmt_pct(fallback['free_tokens'])} Free Available")
        print(f"    • Key Strengths  : {', '.join(fallback['strengths'])}")

    print("=" * 70)


def worktree_selector(worktree: str) -> str:
    """Orca selector for a worktree. A raw id gets the `id:` prefix Orca's own runtime uses,
    which also means the value can never be read as another command-line flag."""
    return worktree if worktree.startswith(WORKTREE_SELECTOR_PREFIXES) else f"id:{worktree}"


def launch_or_switch_agent(
    agent: str,
    model: Optional[str] = None,
    worktree: Optional[str] = None,
    prompt: Optional[str] = None,
    focus: bool = True
) -> bool:
    """Launch or switch to the chosen agent in Orca."""
    args = ["agent", "launch", "--agent", agent]

    if model:
        args.extend(["--model", model])

    if worktree:
        args.extend(["--worktree", worktree_selector(worktree)])

    if prompt:
        args.extend(["--prompt", prompt])

    if focus:
        args.append("--focus")

    args.append("--json")

    # Never write prompt text to the log; it can contain code or secrets
    shown = list(args)
    if prompt:
        shown[shown.index("--prompt") + 1] = f"<{len(prompt)} chars, not logged>"
    log_event(f"Executing Orca agent launch: orca {' '.join(shown)}")

    try:
        run_orca(args, timeout=LAUNCH_TIMEOUT_SECONDS)
    except OrcaTimeout as e:
        log_event(f"{e}. The agent may still have started; check Orca before launching again.")
        return False
    except OrcaUnavailable as e:
        log_event(f"Failed to launch Orca agent: {e}")
        return False
    log_event(f"Successfully switched/launched agent '{agent}' in Orca!")
    return True


def get_current_worktree_id() -> Optional[str]:
    """The Orca worktree containing the current folder, if any (Orca resolves it from the cwd)."""
    try:
        data = run_orca(["worktree", "current", "--json"], timeout=5)
    except OrcaUnavailable:
        return None
    worktree_id = _as_dict(_as_dict(data.get("result")).get("worktree")).get("id")
    return worktree_id if isinstance(worktree_id, str) and worktree_id else None


def list_worktrees() -> List[Dict[str, Any]]:
    """One dict per Orca worktree from `orca worktree ps`, with its raw agent rows. Raises OrcaUnavailable."""
    data = run_orca(["worktree", "ps", "--json"], timeout=10)
    worktrees = []
    for wt in _as_list(_as_dict(data.get("result")).get("worktrees")):
        wt = _as_dict(wt)
        wt_id = wt.get("worktreeId") or wt.get("id")
        if not isinstance(wt_id, str) or not wt_id:
            continue
        worktrees.append({
            "id": wt_id,
            "name": str(wt.get("displayName") or wt.get("branch") or wt.get("path") or wt_id),
            "path": str(wt.get("path") or ""),
            "agents": [_as_dict(a) for a in _as_list(wt.get("agents"))]
        })
    return worktrees


def choose_worktree(explicit: Optional[str]) -> Optional[str]:
    """Worktree for a manual launch: --worktree, else the Orca worktree containing the current folder,
    else a pick list in a console. A .bat runs from this tool's folder, which Orca can't map to a worktree."""
    if explicit:
        return explicit
    current = get_current_worktree_id()
    if current:
        return current
    if sys.stdin is None or not sys.stdin.isatty():
        return None
    try:
        worktrees = list_worktrees()
    except OrcaUnavailable as e:
        print(f"⚠️  Orca worktrees ki list nahi mili: {e}")
        return None
    if not worktrees:
        print("⚠️  Orca me koi worktree nahi mila.")
        return None

    print("\nKis Orca worktree me launch karein?")
    for number, wt in enumerate(worktrees, 1):
        print(f"  [{number}] {wt['name']}  {wt['path']}")
    try:
        answer = input(f"Number chunein (1-{len(worktrees)}): ").strip()
    except EOFError:
        return None
    if answer.isdigit() and 1 <= int(answer) <= len(worktrees):
        return worktrees[int(answer) - 1]["id"]
    print("Galat choice.")
    return None


def send_windows_notification(title: str, message: str) -> None:
    """Send native Windows notification via PowerShell."""
    if sys.platform != "win32":
        return
    run_powershell(TOAST_SCRIPT, {"ORCA_TOAST_TITLE": title, "ORCA_TOAST_MESSAGE": message}, timeout=10)


def confirm_failover(title: str, message: str) -> bool:
    """Ask the user with a Yes/No dialog. Works from pythonw too. Anything but Yes means no."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        MB_YESNO, MB_ICONWARNING, MB_SETFOREGROUND, MB_TOPMOST, IDYES = 0x4, 0x30, 0x10000, 0x40000, 6
        flags = MB_YESNO | MB_ICONWARNING | MB_SETFOREGROUND | MB_TOPMOST
        return ctypes.windll.user32.MessageBoxW(None, message, title, flags) == IDYES
    except Exception:
        return False


def normalize_provider(name: Any) -> Optional[str]:
    """Map an Orca agent/source name such as 'claude' or 'claude-code' onto a MODEL_CATALOG key."""
    if not isinstance(name, str):
        return None
    lowered = name.lower()
    for key, aliases in PROVIDER_ALIASES.items():
        if any(alias in lowered for alias in aliases):
            return key
    return None


def flatten_agents(worktrees: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One dict per agent with its worktree attached, and whether that worktree has a live agent."""
    agents = []
    for wt in worktrees:
        rows = []
        for a in wt["agents"]:
            prompt = a.get("prompt")
            pane_key = a.get("paneKey")
            rows.append({
                "worktree_id": wt["id"],
                "worktree_name": wt["name"],
                "pane_key": pane_key if isinstance(pane_key, str) and pane_key else None,
                "provider": normalize_provider(a.get("agentType")),
                "state": a.get("state"),
                # Orca marks a turn that ended on a StopFailure hook as mainAgent.outcome == "failure"
                "failed": _as_dict(a.get("mainAgent")).get("outcome") == "failure" or a.get("state") in ("error", "failed"),
                "prompt": prompt if isinstance(prompt, str) and prompt.strip() else None
            })
        # Any agent that isn't failed and isn't done (working, waiting on a prompt or permission...) is live
        busy = any(not r["failed"] and r["state"] not in (None, "done") for r in rows)
        for r in rows:
            r["worktree_busy"] = busy
        agents.extend(rows)
    return agents


def read_hook_entries() -> Optional[Dict[str, Dict[str, Any]]]:
    """Read Orca agent-hooks last-status.json. Returns {} if absent, None if it couldn't be read this time."""
    if not ORCA_LAST_STATUS_FILE or not os.path.exists(ORCA_LAST_STATUS_FILE):
        return {}
    try:
        with open(ORCA_LAST_STATUS_FILE, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None  # e.g. Orca was mid-write; the caller keeps the last good copy
    entries = _as_dict(_as_dict(data).get("entries"))
    return {str(pane_key): _as_dict(entry) for pane_key, entry in entries.items()}


def scan_failures(health: Dict[str, Any], agents: List[Dict[str, Any]],
                  hook_entries: Dict[str, Dict[str, Any]], since_ms: float) -> List[Dict[str, Any]]:
    """Every failed agent Orca currently reports, each flagged `actionable` when it needs a backup now:
    its provider is out of quota and nothing else is live in that worktree.

    Non-actionable failures are returned too, so a failure that was handled stays handled while those
    conditions flicker (e.g. the backup agent goes idle, or a quota reading is missing for a poll)."""
    failures: List[Dict[str, Any]] = []
    by_pane = {a["pane_key"]: a for a in agents if a["pane_key"]}
    busy_worktrees = {a["worktree_id"] for a in agents if a["worktree_busy"]}

    # Signal 1: an agent in `orca worktree ps` whose last turn failed
    for a in agents:
        if a["failed"]:
            failures.append({
                "signature": f"wt|{a['worktree_id']}|{a['pane_key']}",
                "event_ms": None,
                "pane_key": a["pane_key"],
                "worktree_id": a["worktree_id"],
                "worktree_name": a["worktree_name"],
                "provider": a["provider"],
                "prompt": a["prompt"]
            })

    # Signal 2: a failed turn reported by Orca's agent hooks after the guardian started
    for pane_key, entry in hook_entries.items():
        received_at = entry.get("receivedAt")
        if isinstance(received_at, bool) or not isinstance(received_at, (int, float)) or received_at <= since_ms:
            continue
        payload = _as_dict(entry.get("payload"))
        error_text = str(payload.get("error") or "").lower().replace("_", " ")
        failed = (entry.get("hookEventName") == "StopFailure"
                  or _as_dict(payload.get("mainAgent")).get("outcome") == "failure"
                  or any(p.search(error_text) for p in RATE_LIMIT_PATTERNS))
        if not failed:
            continue
        agent = by_pane.get(pane_key, {})
        worktree_id = entry.get("worktreeId") if isinstance(entry.get("worktreeId"), str) else agent.get("worktree_id")
        prompt = agent.get("prompt") or payload.get("prompt")
        failures.append({
            "signature": f"hook|{pane_key}|{received_at}",
            "event_ms": received_at,
            "pane_key": pane_key,
            "worktree_id": worktree_id,
            "worktree_name": agent.get("worktree_name") or worktree_id or "unknown worktree",
            "provider": (normalize_provider(payload.get("agentType"))
                         or normalize_provider(entry.get("source"))
                         or agent.get("provider")),
            "prompt": prompt if isinstance(prompt, str) and prompt.strip() else None
        })

    for f in failures:
        provider = f["provider"]
        f["actionable"] = (provider in health and is_exhausted(health[provider])
                           and f["worktree_id"] not in busy_worktrees)
    return failures


def pick_backup(health: Dict[str, Any], exclude: str, allowed: List[str]) -> Optional[str]:
    """Allowed, healthy provider with the most session quota left, other than the failed one."""
    candidates = [
        (key, info) for key, info in health.items()
        if key != exclude and key in allowed and info["status"] in ("HEALTHY", "WARNING")
        and info["session_free"] > MIN_BACKUP_FREE_PERCENT
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda kv: kv[1]["session_free"])[0]


def build_handoff_prompt(failure: Dict[str, Any], failed_name: str, backup_label: str) -> str:
    lines = [f"[Orca auto-failover] The previous agent ({failed_name}) stopped because it hit its usage limit. "
             f"You are taking over on {backup_label}."]
    task = failure.get("prompt")
    if task:
        if len(task) > MAX_HANDOFF_PROMPT_CHARS:
            task = task[:MAX_HANDOFF_PROMPT_CHARS] + "\n[...truncated]"
        lines += ["", "Its original task was:", task, "",
                  "Part of this work may already be done in this worktree. Check git status and git diff first, "
                  "then continue from where it stopped instead of starting over."]
    else:
        lines += ["", "The original task could not be recovered. Look at the recent changes in this worktree "
                      "(git status, git diff), summarise them, and ask the user what to continue with "
                      "before changing anything."]
    return "\n".join(lines)


def perform_failover(failure: Dict[str, Any], health: Dict[str, Any], auto_approve: bool,
                     allowed: List[str], threshold: int) -> str:
    """Launch one backup agent for one failed agent.

    Returns 'launched', 'launch_failed', 'declined', 'skipped' (can't ever act on it) or
    'no_backup' (nothing suitable right now; worth retrying later)."""
    failed_key = failure["provider"]
    wt_name = failure["worktree_name"]

    if failed_key not in MODEL_CATALOG:
        log_event(f"⚠️ Limit hit in '{wt_name}', but the provider couldn't be identified. Not switching.")
        return "skipped"
    failed_name = MODEL_CATALOG[failed_key]["name"]
    if not failure["worktree_id"]:
        log_event(f"⚠️ {failed_name} hit its limit, but its worktree is unknown. Not switching.")
        return "skipped"

    backup_key = pick_backup(health, exclude=failed_key, allowed=allowed)
    if backup_key is None:
        return "no_backup"

    backup = MODEL_CATALOG[backup_key]
    model_key = backup["default_model"]
    backup_label = f"{backup['name']} ({backup['models'][model_key]['label']})"
    free = _fmt_pct(health[backup_key]["session_free"])

    if not auto_approve:
        sent = (f"The original task text will be sent to {backup['name']}." if failure["prompt"]
                else "The original task couldn't be recovered; the new agent will ask you what to continue.")
        question = (f"{failed_name} hit its usage limit in '{wt_name}'.\n\n"
                    f"Continue on {backup_label}? It has {free} quota free.\n\n{sent}")
        if not confirm_failover("Orca Auto-Failover", question):
            log_event(f"Failover for '{wt_name}' to {backup['name']} declined.")
            return "declined"

        # The dialog may have been open for a long time: re-check the backup still has quota
        try:
            fresh = assess_provider_health(get_live_orca_limits(), threshold)
        except OrcaUnavailable as e:
            log_event(f"Orca not reachable after confirmation ({e}). Not switching '{wt_name}' now.")
            return "no_backup"
        if pick_backup(fresh, exclude=failed_key, allowed=[backup_key]) is None:
            log_event(f"{backup['name']} no longer has enough quota. Not switching '{wt_name}' now.")
            return "no_backup"

    log_event(f"🔄 Auto-failover: '{wt_name}' from {failed_name} to {backup_label}, {free} free.")
    ok = launch_or_switch_agent(
        agent=backup_key,
        model=model_key,
        worktree=failure["worktree_id"],
        prompt=build_handoff_prompt(failure, failed_name, backup_label),
        focus=not auto_approve  # only take focus when the user just said yes
    )
    send_windows_notification(
        "Orca Auto-Failover",
        f"Switched '{wt_name}' to {backup['name']}." if ok else f"Couldn't switch '{wt_name}' to {backup['name']}. See the log."
    )
    return "launched" if ok else "launch_failed"


def alert_on_quota_changes(health: Dict[str, Any], alerted: Set[str]) -> None:
    """Notify once when a provider runs out, and log when it recovers. Never launches anything."""
    for key, info in health.items():
        if is_exhausted(info) and key not in alerted:
            alerted.add(key)
            alert_msg = f"{info['name']} reached quota exhaustion ({_fmt_pct(info['session_used'])} used)."
            log_event(f"⚠️ ALERT: {alert_msg}")
            send_windows_notification("Orca Token Limit Alert", alert_msg)
        elif key in alerted and info["status"] in ("HEALTHY", "WARNING"):
            alerted.discard(key)
            log_event(f"✅ {info['name']} has recovered quota ({_fmt_pct(info['session_free'])} free).")


class Guardian:
    """State for the polling loop: each failure is handled once, and at most one launch per cooldown."""

    def __init__(self, threshold: int, cooldown: int, auto_approve: bool, allowed: List[str]):
        self.threshold = threshold
        self.cooldown = cooldown
        self.auto_approve = auto_approve
        self.allowed = allowed
        self.started_ms = time.time() * 1000
        self.handled: Dict[str, int] = {}  # failure signature -> polls it has been missing for
        # pane -> when we handled it. Orca writes the hook file a few seconds after `worktree ps` shows a
        # failure, so a hook entry for that pane received before this time is the same failure.
        self.handled_panes: Dict[str, float] = {}
        self.baseline_taken = False
        self.no_backup_noted: Set[str] = set()
        self.alerted: Set[str] = set()
        self.hook_entries: Dict[str, Dict[str, Any]] = {}
        self.last_launch_at = 0.0
        self.orca_down = False
        self.cooldown_logged = False

    def poll(self) -> None:
        try:
            health = assess_provider_health(get_live_orca_limits(), self.threshold)
            agents = flatten_agents(list_worktrees())
        except OrcaUnavailable as e:
            if not self.orca_down:
                log_event(f"Orca not reachable ({e}). Failover paused until it's back.")
                self.orca_down = True
            return
        if self.orca_down:
            log_event("Orca is reachable again. Failover resumed.")
            self.orca_down = False

        entries = read_hook_entries()
        if entries is not None:
            self.hook_entries = entries

        alert_on_quota_changes(health, self.alerted)

        failures = scan_failures(health, agents, self.hook_entries, self.started_ms)
        self._age_handled({f["signature"] for f in failures})

        # Failures that were already there when the guardian started are not ours to act on
        if not self.baseline_taken:
            self.baseline_taken = True
            for f in failures:
                self.handled[f["signature"]] = 0
            if failures:
                log_event(f"Ignoring {len(failures)} failure(s) from before the guardian started.")

        pending = [f for f in failures if f["actionable"] and not self._already_handled(f)]
        if not pending:
            self.cooldown_logged = False
            return
        if time.time() - self.last_launch_at < self.cooldown:
            if not self.cooldown_logged:
                log_event(f"{len(pending)} failure(s) waiting: switch cooldown active.")
                self.cooldown_logged = True
            return
        self.cooldown_logged = False
        self._handle(pending[0], failures, health)  # at most one switch per poll

    def _already_handled(self, failure: Dict[str, Any]) -> bool:
        if failure["signature"] in self.handled:
            return True
        handled_at = self.handled_panes.get(failure["pane_key"] or "")
        return handled_at is not None and failure["event_ms"] is not None and failure["event_ms"] <= handled_at

    def _age_handled(self, present: Set[str]) -> None:
        """Forget failures that have been gone for a few polls, so a pane failing again later counts again."""
        for signature in list(self.handled):
            if signature in present:
                self.handled[signature] = 0
            else:
                self.handled[signature] += 1
                if self.handled[signature] > FORGET_AFTER_POLLS:
                    del self.handled[signature]
        self.no_backup_noted &= present
        day_ago_ms = time.time() * 1000 - 86_400_000
        self.handled_panes = {pane: at for pane, at in self.handled_panes.items() if at > day_ago_ms}

    def _mark_handled(self, failure: Dict[str, Any], failures: List[Dict[str, Any]]) -> None:
        """This failure, and any other for the same pane or worktree, is dealt with."""
        now_ms = time.time() * 1000
        related = [f for f in failures
                   if (failure["pane_key"] and f["pane_key"] == failure["pane_key"])
                   or (failure["worktree_id"] and f["worktree_id"] == failure["worktree_id"])]
        for f in related + [failure]:
            self.handled[f["signature"]] = 0
            if f["pane_key"]:
                self.handled_panes[f["pane_key"]] = now_ms
        # The `worktree ps` view of this pane may not be visible yet when the hook file reported it first
        if failure["pane_key"] and failure["worktree_id"]:
            self.handled[f"wt|{failure['worktree_id']}|{failure['pane_key']}"] = 0

    def _handle(self, failure: Dict[str, Any], failures: List[Dict[str, Any]], health: Dict[str, Any]) -> None:
        outcome = "error"
        try:
            outcome = perform_failover(failure, health, self.auto_approve, self.allowed, self.threshold)
        finally:
            # Bookkeeping runs even if something above raised, so the same failure isn't retried every poll
            if outcome == "no_backup":
                if failure["signature"] not in self.no_backup_noted:
                    self.no_backup_noted.add(failure["signature"])
                    msg = (f"{MODEL_CATALOG[failure['provider']]['name']} hit its limit in '{failure['worktree_name']}', "
                           f"and no allowed provider has more than {MIN_BACKUP_FREE_PERCENT}% quota free. Will retry.")
                    log_event(f"❌ {msg}")
                    send_windows_notification("Orca Auto-Failover", msg)
            else:
                self._mark_handled(failure, failures)
            if outcome in ("launched", "launch_failed", "error"):
                self.last_launch_at = time.time()


def acquire_guardian_lock() -> Optional[Any]:
    """Hold an exclusive lock for the life of the process so only one guardian runs. None if taken."""
    os.makedirs(DATA_DIR, exist_ok=True)
    handle = open(GUARDIAN_LOCK_FILE, "a+b")
    try:
        if sys.platform == "win32":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def run_auto_guard_sentinel(poll_interval: int = 15, threshold: int = DEFAULT_THRESHOLD,
                            cooldown: int = DEFAULT_COOLDOWN_SECONDS, auto_approve: bool = False,
                            allowed: Optional[List[str]] = None) -> int:
    """Background loop: alert on quota exhaustion, and offer one backup agent when an agent fails on its limit."""
    allowed = allowed or list(MODEL_CATALOG)
    lock = acquire_guardian_lock()
    if lock is None:
        print("🛑 Ek Orca Guardian pehle se chal raha hai. Doosra start nahi kiya.")
        return 1

    print("\n🛡️  ORCA AUTO-FAILOVER GUARDIAN STARTED")
    print(f"Monitoring every {poll_interval}s. Exhausted at >= {threshold}% session use.")
    print(f"Switch targets allowed: {', '.join(allowed)}. Cooldown between switches: {cooldown}s.")
    print("Switching mode: " + ("automatic (no confirmation)" if auto_approve else "asks you first (Yes/No dialog)"))
    print(f"Log: {FAILOVER_LOG_FILE}")
    print("Press Ctrl+C to stop.\n")
    if not auto_approve and sys.platform != "win32":
        log_event("Confirmation dialogs need Windows, so every failover will be declined. Use --auto to allow them.")

    guardian = Guardian(threshold, cooldown, auto_approve, allowed)
    last_error = None
    try:
        while True:
            try:
                guardian.poll()
                last_error = None
            except Exception as e:
                if str(e) != last_error:
                    log_event(f"Error in Guardian loop: {e}")
                    last_error = str(e)
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        print("\n🛑 Orca Guardian stopped.")
        return 0
    finally:
        lock.close()


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stop_running_guardians() -> int:
    """Stop guardian processes only (matched by command line). Returns how many, or -1 on error."""
    ok, stdout, stderr = run_powershell(STOP_GUARDIANS_SCRIPT, {})
    if not ok:
        print(f"⚠️  Running guardian check nahi ho paya: {stderr or stdout}")
        return -1
    lines = stdout.splitlines()
    return int(lines[-1]) if lines and lines[-1].strip().isdigit() else 0


def install_autostart(guard_args: List[str]) -> int:
    """Copy this script to the local data folder and start it at login, hidden, via pythonw."""
    if sys.platform != "win32":
        print("Auto-start sirf Windows par available hai.")
        return 1

    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.isfile(pythonw):
        print(f"❌ pythonw.exe nahi mila ({sys.executable} ke saath). python.org se Python install karke dobara chalayein.")
        return 1

    if any(marker in CURRENT_DIR.lower() for marker in SYNCED_FOLDER_MARKERS):
        print("ℹ️  Ye folder cloud-sync wala lagta hai. Guardian iski ek local copy chalayega, taaki is")
        print("    folder me koi badlaav login par apne aap na chale.")

    stopped = stop_running_guardians()
    if stopped < 0:
        print("❌ Pehle se chal rahe guardian ko check/band nahi kar paye, isliye install roka gaya.")
        print("   6_Disable_Guardian_Auto_Start.bat chalayein ya PC restart karke dobara try karein.")
        return 1
    if stopped > 0:
        print(f"Purana chal raha guardian band kiya ({stopped}).")

    os.makedirs(DATA_DIR, exist_ok=True)
    source = os.path.abspath(__file__)
    installed = os.path.join(DATA_DIR, os.path.basename(source))
    if os.path.normcase(source) != os.path.normcase(installed):
        shutil.copy2(source, installed)

    ok, stdout, stderr = run_powershell(CREATE_SHORTCUT_SCRIPT, {
        "ORCA_LNK_NAME": STARTUP_SHORTCUT_NAME,
        "ORCA_OLD_LNK_NAMES": "|".join(OLD_SHORTCUT_NAMES),
        "ORCA_TARGET": pythonw,
        "ORCA_ARGS": subprocess.list2cmdline([installed, "guard", *guard_args]),
        "ORCA_WORKDIR": DATA_DIR
    })
    if not ok:
        print(f"❌ Startup shortcut nahi ban paya: {stderr or stdout}")
        return 1

    subprocess.Popen(
        [pythonw, installed, "guard", *guard_args],
        cwd=DATA_DIR,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        close_fds=True
    )

    print("✅ Auto-start on. Guardian ab background me chal raha hai aur har login par chalega.")
    print(f"   Installed copy : {installed}")
    print(f"   SHA-256        : {file_sha256(installed)}")
    print(f"   Log            : {FAILOVER_LOG_FILE}")
    print("   Is folder ke script me badlaav karein toh ye installer dobara chalayein.")
    return 0


def uninstall_autostart() -> int:
    """Remove the Startup shortcut (new and old names), stop guardians, and delete the installed copy."""
    if sys.platform != "win32":
        print("Auto-start sirf Windows par available hai.")
        return 1

    ok, stdout, stderr = run_powershell(REMOVE_SHORTCUTS_SCRIPT, {
        "ORCA_LNK_NAMES": "|".join([STARTUP_SHORTCUT_NAME, *OLD_SHORTCUT_NAMES])
    })
    if ok:
        removed = stdout.splitlines()[-1].strip() if stdout else "0"
        print("✅ Startup shortcut hata diya." if removed not in ("", "0") else "ℹ️  Startup shortcut nahi mila.")
    else:
        print(f"⚠️  Startup shortcut hatane me dikkat: {stderr or stdout}")

    stopped = stop_running_guardians()
    if stopped >= 0:
        print(f"✅ Background guardian band kiya ({stopped})." if stopped else "ℹ️  Koi guardian chal nahi raha tha.")

    installed = os.path.join(DATA_DIR, os.path.basename(os.path.abspath(__file__)))
    if os.path.isfile(installed) and os.path.normcase(installed) != os.path.normcase(os.path.abspath(__file__)):
        try:
            os.remove(installed)
        except OSError as e:
            print(f"⚠️  Installed copy delete nahi hui: {e}")
    print(f"ℹ️  Log files yahan hain (chahein toh delete karein): {DATA_DIR}")
    return 0 if ok and stopped >= 0 else 1


def int_in_range(low: int, high: int):
    def parse(value: str) -> int:
        try:
            number = int(value)
        except ValueError:
            raise argparse.ArgumentTypeError(f"{value!r} is not a whole number")
        if not low <= number <= high:
            raise argparse.ArgumentTypeError(f"must be between {low} and {high}")
        return number
    return parse


def provider_list(value: str) -> List[str]:
    names = [name.strip().lower() for name in value.split(",") if name.strip()]
    unknown = [name for name in names if name not in MODEL_CATALOG]
    if not names or unknown:
        raise argparse.ArgumentTypeError(f"use a comma-separated list from: {', '.join(MODEL_CATALOG)}")
    return names


def main() -> int:
    parser = argparse.ArgumentParser(description="Orca Smart Model Switcher & Auto-Failover System")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    threshold_option = argparse.ArgumentParser(add_help=False)
    threshold_option.add_argument("--threshold", type=int_in_range(1, 100), default=DEFAULT_THRESHOLD,
                                  help="Session %% used at which a provider counts as exhausted")

    worktree_option = argparse.ArgumentParser(add_help=False)
    worktree_option.add_argument("--worktree", type=str, default=None,
                                 help="Orca worktree to launch in (id, or a selector like name:<name>). "
                                      "Default: the worktree you're in, else a pick list")

    guard_options = argparse.ArgumentParser(add_help=False, parents=[threshold_option])
    guard_options.add_argument("--interval", type=int_in_range(5, 3600), default=15, help="Polling interval in seconds")
    guard_options.add_argument("--cooldown", type=int_in_range(0, 86400), default=DEFAULT_COOLDOWN_SECONDS,
                               help="Minimum seconds between two automatic switches")
    guard_options.add_argument("--auto", action="store_true",
                               help="Switch without asking first (the task text is sent to the backup provider automatically)")
    guard_options.add_argument("--allow", type=provider_list, default=list(MODEL_CATALOG),
                               help="Comma-separated providers the guardian may switch to, e.g. claude,codex")

    # Command: status
    subparsers.add_parser("status", parents=[threshold_option], help="Show live token dashboard for all models")

    # Command: best
    best_parser = subparsers.add_parser("best", parents=[threshold_option, worktree_option],
                                        help="Find & recommend the best model for a task")
    best_parser.add_argument("task", type=str, nargs="?", help="Description of the task or prompt (asked for if left out)")
    best_parser.add_argument("--launch", action="store_true", help="Automatically switch/launch the top recommended model")
    best_parser.add_argument("--interactive", action="store_true", help="Ask for the task and whether to launch")

    # Command: switch
    switch_parser = subparsers.add_parser("switch", parents=[worktree_option], help="Switch model or agent in Orca")
    switch_parser.add_argument("agent", type=str, choices=list(MODEL_CATALOG), help="Target agent")
    switch_parser.add_argument("--model", type=str, default=None, help="Target model id/slug")
    switch_parser.add_argument("--prompt", type=str, default=None, help="Optional initial prompt")

    # Command: guard
    subparsers.add_parser("guard", parents=[guard_options], help="Start background auto-failover sentinel")

    # Commands: auto-start on/off (Windows)
    subparsers.add_parser("install-autostart", parents=[guard_options], help="Run the guardian at every Windows login")
    subparsers.add_parser("uninstall-autostart", help="Stop the guardian and remove it from Windows login")

    args = parser.parse_args()
    command = args.command or "status"
    threshold = getattr(args, "threshold", DEFAULT_THRESHOLD)
    no_worktree_help = ("❌ Orca worktree nahi mila. Orca ke kisi worktree ke andar se chalayein, "
                        "ya --worktree dein (orca worktree ps se id milegi).")

    if command == "status":
        health, error = fetch_health(threshold)
        print_status_dashboard(health, error)
        return 0 if error is None else 2

    if command == "best":
        task = (args.task or "").strip()
        interactive = args.interactive or not task
        if not task:
            try:
                task = input("Aap kis tarah ka task karna chahte hain? (Task description likhein): ").strip()
            except EOFError:
                task = ""
            if not task:
                print("Task description khali nahi ho sakti.")
                return 1

        health, error = fetch_health(threshold)
        rec = recommend_best_model_for_task(task, health)
        top = rec["recommended"]
        print_recommendation(task, rec, error)

        launch = args.launch
        if not launch and interactive:
            try:
                answer = input("\nKya aap is Recommended Model ko Orca me abhi switch/launch karna chahte hain? (Y/N): ")
            except EOFError:
                answer = ""
            launch = answer.strip().lower() in ("y", "yes", "haan", "ha")
            if not launch:
                print("Launch cancel kiya gaya.")
                return 0
        if not launch:
            print("\n💡 To switch to this model right now, run:")
            print(f"   python {os.path.basename(__file__)} switch {top['agent']} --model {top['model_key']}\n")
            return 0

        if not top["quota_known"]:
            print(f"\n⚠️  {top['provider_name']} ka quota pata nahi chala, isliye launch nahi kiya.")
            print(f"   Phir bhi chahiye toh: python {os.path.basename(__file__)} switch {top['agent']} --model {top['model_key']}")
            return 1
        if top["final_score"] <= 0:
            print("\n❌ Sabhi models ke tokens khatam hain. Reset ka intezaar karein.")
            return 1

        worktree = choose_worktree(args.worktree)
        if not worktree:
            print(no_worktree_help)
            return 1
        print(f"\n🚀 Launching {top['label']} in Orca...")
        ok = launch_or_switch_agent(agent=top["agent"], model=top["model_key"], worktree=worktree, focus=True)
        print("✅ Model switch complete! Orca tab me check karein." if ok
              else f"❌ Launch nahi ho paya. Log dekhein: {FAILOVER_LOG_FILE}")
        return 0 if ok else 1

    if command == "switch":
        worktree = choose_worktree(args.worktree)
        if not worktree:
            print(no_worktree_help)
            return 1
        print(f"Switching to {args.agent} (model: {args.model or 'default'})...")
        ok = launch_or_switch_agent(
            agent=args.agent,
            model=args.model,
            worktree=worktree,
            prompt=args.prompt,
            focus=True
        )
        return 0 if ok else 1

    if command == "guard":
        return run_auto_guard_sentinel(poll_interval=args.interval, threshold=threshold, cooldown=args.cooldown,
                                       auto_approve=args.auto, allowed=args.allow)

    if command == "install-autostart":
        guard_args = ["--interval", str(args.interval), "--threshold", str(threshold),
                      "--cooldown", str(args.cooldown), "--allow", ",".join(args.allow)]
        if args.auto:
            guard_args.append("--auto")
        return install_autostart(guard_args)

    if command == "uninstall-autostart":
        return uninstall_autostart()

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
