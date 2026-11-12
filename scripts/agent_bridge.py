"""Bounded non-interactive Codex / Claude Code invocation; no API keys required here."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from core import ROOT

FINDING_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "kind": {"type": "string", "enum": ["bugfix", "security", "performance", "config", "refactor", "feature", "ux", "other"]},
        "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
        "risk": {"type": "string", "enum": ["low", "medium", "high", "uncertain"]},
        "confidence": {"type": "number"},
        "why": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "file_hints": {"type": "array", "items": {"type": "string"}},
        "fix_instructions": {"type": "string"},
        "watch_markers": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "kind", "severity", "risk", "confidence", "why", "evidence", "file_hints", "fix_instructions", "watch_markers"],
}
ANALYSIS_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "overall_health": {"type": "string", "enum": ["healthy", "needs_attention", "critical", "unknown"]},
        "findings": {"type": "array", "items": FINDING_SCHEMA},
        "monitor_notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "overall_health", "findings", "monitor_notes"],
}


def _invoke(cmd: list[str], cwd: Path, prompt: str, timeout: int) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, input=prompt, cwd=cwd, text=True, encoding="utf-8",
                              capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"AI CLI timed out after {timeout}s") from e
    except FileNotFoundError as e:
        raise RuntimeError(f"AI CLI missing: {cmd[0]} (install and log in first)") from e


def run_analysis(engine: str, cwd: Path, prompt: str, timeout: int) -> dict[str, Any]:
    """Read-only analysis, with structured output from either local subscription CLI."""
    if shutil.which(engine) is None:
        raise RuntimeError(f"{engine} CLI not on PATH. Run `doctor` and log in separately.")
    if engine == "codex":
        with tempfile.TemporaryDirectory(prefix="maint-analysis-") as tmp:
            schema_path = Path(tmp) / "schema.json"
            answer_path = Path(tmp) / "response.json"
            schema_path.write_text(json.dumps(ANALYSIS_SCHEMA), encoding="utf-8")
            cmd = ["codex", "exec", "--skip-git-repo-check", "--sandbox", "read-only",
                   "--ask-for-approval", "never", "--output-schema", str(schema_path),
                   "--output-last-message", str(answer_path), "-"]
            result = _invoke(cmd, cwd, prompt, timeout)
            if result.returncode != 0 or not answer_path.exists():
                raise RuntimeError(f"Codex analysis failed ({result.returncode}): {result.stderr[-1200:]}")
            data = json.loads(answer_path.read_text(encoding="utf-8"))
    else:
        cmd = ["claude", "--safe-mode", "--restricted", "-p", "--permission-mode", "plan", "--permission-prompts", "none",
               "--tools", "Read,Glob,Grep", "--allowedTools", "Read,Glob,Grep",
               "--output-format", "json", "--json-schema", json.dumps(ANALYSIS_SCHEMA),
               "Analyze the application using the full task instructions and evidence piped to stdin. Return structured output."]
        result = _invoke(cmd, cwd, prompt, timeout)
        if result.returncode != 0:
            raise RuntimeError(f"Claude analysis failed ({result.returncode}): {result.stderr[-1200:]} {result.stdout[-500:]}")
        response = json.loads(result.stdout)
        data = response.get("structured_output")
        if data is None:
            data = json.loads(response["result"])
    if not isinstance(data, dict) or not isinstance(data.get("findings"), list):
        raise RuntimeError("AI response did not match analysis schema")
    return data


def run_patch(engine: str, cwd: Path, prompt: str, timeout: int) -> str:
    """Edit a *temporary working copy*, never the real app. Runner validates the diff."""
    if shutil.which(engine) is None:
        raise RuntimeError(f"{engine} CLI not on PATH")
    if engine == "codex":
        with tempfile.TemporaryDirectory(prefix="maint-patch-") as tmp:
            out = Path(tmp) / "result.txt"
            cmd = ["codex", "exec", "--skip-git-repo-check", "--sandbox", "workspace-write",
                   "--ask-for-approval", "never", "--output-last-message", str(out), "-"]
            result = _invoke(cmd, cwd, prompt, timeout)
            if result.returncode:
                raise RuntimeError(f"Codex patch failed ({result.returncode}): {result.stderr[-1200:]}")
            return out.read_text(encoding="utf-8")[:1000] if out.exists() else "Patch complete"
    cmd = ["claude", "--safe-mode", "--restricted", "-p", "--permission-mode", "acceptEdits", "--permission-prompts", "none",
           "--tools", "Read,Edit,Write,Glob,Grep", "--allowedTools", "Read,Edit,Write,Glob,Grep",
           "--output-format", "json", "Follow the implementation task piped to stdin. Edit only the current staging copy."]
    result = _invoke(cmd, cwd, prompt, timeout)
    if result.returncode:
        raise RuntimeError(f"Claude patch failed ({result.returncode}): {result.stderr[-1200:]} {result.stdout[-500:]}")
    response = json.loads(result.stdout)
    return str(response.get("result", "Patch complete"))[:1000]


def load_prompt(name: str) -> str:
    return (ROOT / "references" / name).read_text(encoding="utf-8")
