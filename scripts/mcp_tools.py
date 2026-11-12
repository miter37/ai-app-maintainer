"""MCP tool facade over the existing ai-app-maintainer CLI and local state.

No network listener, GUI, direct AI API access, or third-party dependencies.
Mutating operations reuse the CLI's exclusive maintenance lock and policy checks.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import deque
from pathlib import Path
from typing import Any

from core import (ROOT, DEFAULTS, app_dir, app_path, app_settings, collect_logs,
                  config, load_json, redact, registry, validate_slug)
from workflow import read_monitors, active_monitors, eligible_to_run

MAX_RESULT_CHARS = 55000
PROPOSAL_ID_RE = re.compile(r"[a-f0-9]{14}\Z")


def _schema(properties: dict[str, dict], required: tuple[str, ...] = ()) -> dict:
    return {"type": "object", "properties": properties, "required": list(required),
            "additionalProperties": False}


def _string(description: str, max_length: int = 1000) -> dict:
    return {"type": "string", "description": description, "maxLength": max_length}


def _bool(description: str) -> dict:
    return {"type": "boolean", "description": description}


def _app_id() -> dict:
    return {"type": "string", "pattern": "^[a-z][a-z0-9-]{0,48}$", "description": "Registered app ID."}


def _tool(name: str, description: str, properties: dict[str, dict] | None = None,
          required: tuple[str, ...] = (), *, read_only: bool = False,
          destructive: bool = False, idempotent: bool = False) -> dict:
    return {"name": name, "description": description,
            "inputSchema": _schema(properties or {}, required),
            "annotations": {"readOnlyHint": read_only, "destructiveHint": destructive,
                            "idempotentHint": idempotent, "openWorldHint": False}}


TOOLS = [
    _tool("maintenance_help", "Explain how to use this MCP and how human approvals work. Does not change any files.", read_only=True),
    _tool("list_apps", "List registered local applications with short health and due status. No code changes.", read_only=True),
    _tool("get_settings", "Read global settings and effective settings for one app, including MCP write gates.",
          {"app_id": _app_id()}, read_only=True),
    _tool("get_app_status", "Read latest app status, pending count and post-fix watches without initiating maintenance.",
          {"app_id": _app_id()}, ("app_id",), read_only=True),
    _tool("get_history", "Read bounded recent per-app maintenance audit events.",
          {"app_id": _app_id(), "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25}},
          ("app_id",), read_only=True),
    _tool("get_pending_changes", "List approval-required fixes/features and their immutable proposal IDs. Never approves.",
          {"app_id": _app_id()}, read_only=True),
    _tool("get_change_details", "Inspect a specific pending proposal and its evidence. Never approves or applies.",
          {"app_id": _app_id(), "proposal_id": {"type": "string", "pattern": "^[a-f0-9]{14}$"}},
          ("app_id", "proposal_id"), read_only=True),
    _tool("get_post_fix_monitoring", "Return current and historical multi-day post-fix watches with regression signals.",
          {"app_id": _app_id()}, ("app_id",), read_only=True),
    _tool("get_latest_report", "Read the most recent app maintenance or feature-suggestion report.",
          {"app_id": _app_id(), "report_type": {"type": "string", "enum": ["maintenance", "suggestions"],
                                              "default": "maintenance"}}, ("app_id",), read_only=True),
    _tool("inspect_logs", "Collect a bounded/redacted preview of recent registered logs. Does NOT call AI or edit source.",
          {"app_id": _app_id(), "preview_lines": {"type": "integer", "minimum": 1, "maximum": 30, "default": 10}},
          ("app_id",), read_only=True),
    _tool("run_maintenance", "Run due (default), all, or one app through its registered Codex/Claude CLI. WARNING: if auto_fix=true, safe narrow source patches MAY be applied; never feature/UX proposals. Affected code can change. Requires mcp_allow_execution=true.",
          {"app_id": _app_id(), "due_only": _bool("If no app_id: only run due apps (default true); false runs every app."),
           "observe_only": _bool("True: no AI analysis or patches, but collect logs and rerun post-fix tests.")},
          destructive=True),
    _tool("suggest_improvements", "Ask the AI to propose new features, menus, or UX changes for a registered app. Always approval-gated; NEVER implements them. Requires mcp_allow_execution=true.",
          {"app_id": _app_id()}, ("app_id",), destructive=False),
    _tool("apply_approved_change", "Implement ONLY an already human-approved proposal by exact ID, using staged patch/test/rollback policy. This tool CANNOT approve proposals. Requires prior local-CLI approval and mcp_allow_execution=true.",
          {"app_id": _app_id(), "proposal_id": {"type": "string", "pattern": "^[a-f0-9]{14}$"}},
          ("app_id", "proposal_id"), destructive=True),
    _tool("register_app", "REGISTER an app root (opt-in, mcp_allow_registration=false by default). Log patterns and tests are operator-defined. Requires permission to register the folder; never inspect outside that root.",
          {"app_id": _app_id(), "path": _string("Absolute existing app folder path.", 2048),
           "log_patterns": {"type": "array", "items": _string("Relative glob", 256), "maxItems": 12},
           "test_commands": {"type": "array", "items": _string("Argv-style test command (not a shell pipeline)", 512), "maxItems": 6},
           "notes": _string("Brief app notes", 1200)}, ("app_id", "path"), destructive=True),
    _tool("set_app_setting", "Change one approved per-app option (opt-in, mcp_allow_settings_changes=false by default). Cannot self-enable MCP write permissions.",
          {"app_id": _app_id(), "key": {"type": "string", "enum": ["enabled", "auto_fix", "upgrade_suggestions",
              "lookback_hours", "run_every_hours", "monitor_days", "monitor_check_every_hours", "monitor_run_tests", "notes"]},
           "value": {"type": "string", "maxLength": 1200}}, ("app_id", "key", "value"), destructive=True),
    _tool("set_global_setting", "Change a maintenance option (opt-in, mcp_allow_settings_changes=false by default). Security and MCP permission toggles are NOT writable via MCP.",
          {"key": {"type": "string", "enum": ["engine", "auto_fix", "upgrade_suggestions", "lookback_hours",
              "run_every_hours", "monitor_days", "monitor_check_every_hours", "monitor_run_tests", "min_auto_confidence"]},
           "value": {"type": "string", "maxLength": 60}}, ("key", "value"), destructive=True),
]
BY_NAME = {t["name"]: t for t in TOOLS}


class ToolError(ValueError):
    """A model-visible, redacted, bounded operational error."""


def _validate(name: str, args: Any) -> dict[str, Any]:
    if name not in BY_NAME:
        raise ToolError(f"Unknown MCP tool: {name}")
    if not isinstance(args, dict):
        raise ToolError("Tool arguments must be a JSON object")
    schema = BY_NAME[name]["inputSchema"]
    allowed = schema["properties"]
    extras = set(args) - set(allowed)
    if extras:
        raise ToolError(f"Unexpected argument(s): {', '.join(sorted(extras))}")
    missing = [k for k in schema["required"] if k not in args]
    if missing:
        raise ToolError(f"Missing argument(s): {', '.join(missing)}")
    for k, val in args.items():
        prop = allowed[k]
        typ = prop["type"]
        if typ == "string" and not isinstance(val, str):
            raise ToolError(f"{k} must be a string")
        if typ == "boolean" and type(val) is not bool:
            raise ToolError(f"{k} must be true or false")
        if typ == "integer" and (type(val) is not int or not prop.get("minimum", -1) <= val <= prop.get("maximum", 10**10)):
            raise ToolError(f"{k} must be an integer within the allowed range")
        if typ == "array" and (not isinstance(val, list) or len(val) > prop.get("maxItems", 50)):
            raise ToolError(f"{k} must be an array within the allowed size")
        if typ == "array":
            if any(not isinstance(x, str) or len(x) > prop["items"].get("maxLength", 10000) for x in val):
                raise ToolError(f"{k} has invalid items")
        if typ == "string":
            if len(val) > prop.get("maxLength", 10000) or ("enum" in prop and val not in prop["enum"]):
                raise ToolError(f"{k} is not an allowed value")
            if "pattern" in prop and not re.fullmatch(prop["pattern"], val):
                raise ToolError(f"{k} has an invalid format")
    return args


def _app(app_id: str) -> tuple[dict, dict]:
    validate_slug(app_id)
    found = registry()["apps"].get(app_id)
    if found is None:
        raise ToolError(f"Unknown app: {app_id}. Use list_apps or register it locally first.")
    return found, app_settings(found, config())


def _proposal_id(proposal_id: str) -> str:
    if not isinstance(proposal_id, str) or not PROPOSAL_ID_RE.fullmatch(proposal_id):
        raise ToolError("Invalid proposal ID; use an exact ID returned by get_pending_changes")
    return proposal_id


def _gate(key: str) -> None:
    if config().get(key) is not True:
        raise ToolError(f"Denied by local config: {key}=false. Only the operator can enable this with the local CLI.")


def _cli(args: list[str], *, long_running: bool = False) -> Any:
    cfg = config()
    registered = len(registry()["apps"])
    per_app = int(cfg["agent_timeout_seconds"]) * 3 + int(cfg["test_timeout_seconds"]) * 3 + 30
    timeout = min(7200, max(60, per_app * min(10, max(1, registered)))) if long_running else 45
    try:
        result = subprocess.run([sys.executable, str(ROOT / "scripts" / "maintainer.py"), *args],
                                cwd=ROOT, text=True, encoding="utf-8", errors="replace",
                                capture_output=True, shell=False, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"Maintenance command exceeded {timeout}s; inspect local lock and audit files before retrying") from exc
    if result.returncode:
        # run --due can return 2 while still reporting useful per-app results.
        if args and args[0] == "run" and result.stdout.strip():
            try:
                return {"status": "completed_with_errors", "results": json.loads(result.stdout)}
            except json.JSONDecodeError:
                pass
        msg = redact(result.stderr.strip() or result.stdout.strip())[-1000:]
        raise ToolError(f"Maintenance command failed (exit {result.returncode}): {msg}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ToolError("Maintenance command returned unexpected non-JSON output") from exc


def _bounded(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        payload = {"result": payload}
    serial = json.dumps(payload, ensure_ascii=False, default=str)
    if len(serial) > MAX_RESULT_CHARS:
        return {"truncated": True, "message": "Result exceeded MCP size cap; request a narrower app or history range.",
                "preview": serial[:MAX_RESULT_CHARS // 2]}
    return payload


def dispatch(name: str, arguments: Any) -> dict[str, Any]:
    """Server-independent tool handler for testing and transport adapters."""
    args = _validate(name, arguments)
    if name == "maintenance_help":
        return {"name": "ai-app-maintainer", "transport": "local_stdio", "always_on": False,
                "summary": "Logs -> bounded AI diagnosis -> safe auto bugfix or human approval -> five-day post-fix watches.",
                "example": "run_maintenance({}) checks due apps; get_pending_changes({}) lists decisions.",
                "human_approval": "MCP cannot authorize changes. Operator must execute: python3 scripts/maintainer.py approve --app APP --id PROPOSAL --no-apply; then call apply_approved_change or run_maintenance.",
                "scheduling": "Use Hermes/OpenClaw cron or OS scheduler; MCP does not run a daemon on its own.",
                "configuration": "Operator-controlled config.json and registry.json. MCP write gates default to restricted."}
    if name == "list_apps":
        out = []
        for app_id, app in sorted(registry()["apps"].items()):
            settings = app_settings(app, config())
            state = load_json(app_dir(app_id) / "status.json", {})
            out.append({"id": app_id, "path": app.get("path"), "enabled": app.get("enabled", True),
                        "auto_fix": settings["auto_fix"], "upgrade_suggestions": settings["upgrade_suggestions"],
                        "health": state.get("health", "unknown"), "last_run_at": state.get("last_run_at"),
                        "due": bool(app.get("enabled", True) and eligible_to_run(app_id, settings)),
                        "active_watches": len(active_monitors(app_id))})
        return {"apps": out, "count": len(out)}
    if name == "get_settings":
        cfg = config()
        if args.get("app_id"):
            app, settings = _app(args["app_id"])
            return {"app_id": args["app_id"], "app_settings": settings, "global_settings": cfg}
        return {"global_settings": cfg, "registered_count": len(registry()["apps"])}
    if name == "get_app_status":
        _, settings = _app(args["app_id"])
        app_id = args["app_id"]
        state = load_json(app_dir(app_id) / "status.json", {})
        pending_count = sum(1 for p in (app_dir(app_id) / "proposals").glob("*.json")
                            if load_json(p, {}).get("status") in ("pending_auto", "pending_approval", "approved"))
        return {"app_id": app_id, "state": state, "pending_count": pending_count,
                "due": eligible_to_run(app_id, settings),
                "monitors": [{k: m.get(k) for k in ("fix_id", "title", "status", "until_at", "last_checked_at", "observation_count", "test_fail_count")}
                             for m in read_monitors(app_id)[:100]]}
    if name == "get_history":
        _app(args["app_id"])
        limit = args.get("limit", 25)
        path = app_dir(args["app_id"]) / "history.jsonl"
        if not path.exists():
            return {"app_id": args["app_id"], "events": []}
        with path.open(encoding="utf-8", errors="replace") as f:
            lines = deque(f, maxlen=limit)
        return {"app_id": args["app_id"], "events": [json.loads(line) for line in lines if line.strip()]}
    if name == "get_pending_changes":
        ids = [args["app_id"]] if args.get("app_id") else sorted(registry()["apps"])
        entries = []
        for app_id in ids:
            _app(app_id)
            for path in sorted((app_dir(app_id) / "proposals").glob("*.json")):
                p = load_json(path, {})
                if p.get("status") in ("pending_auto", "pending_approval", "approved"):
                    entries.append({"app_id": app_id, **{k: p.get(k) for k in
                        ("id", "title", "kind", "risk", "confidence", "status", "reason", "last_error", "first_seen_at")}})
        return {"pending": entries[:200], "total": len(entries), "truncated": len(entries) > 200,
                "approval_rule": "No MCP tool can approve. Human must use local maintainer.py approve --no-apply."}
    if name == "get_change_details":
        _app(args["app_id"])
        proposal_id = _proposal_id(args["proposal_id"])
        data = load_json(app_dir(args["app_id"]) / "proposals" / (proposal_id + ".json"))
        if data is None:
            raise ToolError("Proposal not found")
        return {"app_id": args["app_id"], "proposal": data,
                "approval_command": f"python3 scripts/maintainer.py approve --app {args['app_id']} --id {proposal_id} --no-apply"}
    if name == "get_post_fix_monitoring":
        _app(args["app_id"])
        return {"app_id": args["app_id"], "monitors": read_monitors(args["app_id"])[:100]}
    if name == "get_latest_report":
        _app(args["app_id"])
        report_name = "latest-suggestions.md" if args.get("report_type", "maintenance") == "suggestions" else "latest-report.md"
        path = app_dir(args["app_id"]) / report_name
        if not path.exists():
            return {"app_id": args["app_id"], "found": False, "report_type": args.get("report_type", "maintenance")}
        body = path.read_text(encoding="utf-8", errors="replace")
        return {"app_id": args["app_id"], "found": True, "report": redact(body[:22000]),
                "truncated": len(body) > 22000}
    if name == "inspect_logs":
        app, settings = _app(args["app_id"])
        evidence = collect_logs(app_path(app), settings["log_globs"], settings["lookback_hours"], settings)
        evidence["records"] = evidence["records"][-args.get("preview_lines", 10):]
        return {"app_id": args["app_id"], "evidence": evidence}
    if name == "run_maintenance":
        _gate("mcp_allow_execution")
        app_id = args.get("app_id")
        command = ["run", "--app", app_id] if app_id else ["run", "--due" if args.get("due_only", True) else "--all"]
        if app_id:
            _app(app_id)
        if args.get("observe_only", False):
            command.append("--no-agent")
        return {"operation": "run_maintenance", "result": _cli(command, long_running=True),
                "warning": "AI analysis may apply narrow bugfixes if auto_fix=true; no deployment/restart performed."}
    if name == "suggest_improvements":
        _gate("mcp_allow_execution")
        _app(args["app_id"])
        return {"operation": "suggest_improvements", "result": _cli(["suggest", "--app", args["app_id"]], long_running=True),
                "approval": "Feature/menu/UX suggestions are never auto-implemented."}
    if name == "apply_approved_change":
        _gate("mcp_allow_execution")
        _app(args["app_id"])
        proposal_id = _proposal_id(args["proposal_id"])
        p = load_json(app_dir(args["app_id"]) / "proposals" / (proposal_id + ".json"))
        if p is None or p.get("status") != "approved":
            raise ToolError("Not already human-approved. Request operator to run local CLI approve --no-apply first.")
        return {"operation": "apply_approved_change", "result": _cli(["apply-approved", "--app", args["app_id"], "--id", proposal_id], long_running=True)}
    if name == "register_app":
        _gate("mcp_allow_registration")
        command = ["add", "--app", args["app_id"], "--path", args["path"]]
        for glob in args.get("log_patterns", []):
            command.extend(["--log", glob])
        for test in args.get("test_commands", []):
            command.extend(["--test", test])
        if args.get("notes"):
            command.extend(["--notes", args["notes"]])
        return {"operation": "register_app", "result": _cli(command)}
    if name == "set_app_setting":
        _gate("mcp_allow_settings_changes")
        _app(args["app_id"])
        return {"operation": "set_app_setting", "result": _cli(["set-app", "--app", args["app_id"],
                                                                  "--key", args["key"], "--value", args["value"]])}
    if name == "set_global_setting":
        _gate("mcp_allow_settings_changes")
        return {"operation": "set_global_setting", "result": _cli(["config", "--key", args["key"], "--value", args["value"]])}
    raise ToolError(f"Unimplemented tool: {name}")


def call(name: str, arguments: Any) -> dict[str, Any]:
    """Always return a compact structured response, errors included for the MCP adapter."""
    try:
        return _bounded({"ok": True, **dispatch(name, arguments)})
    except (KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": redact(str(exc))[:1500], "tool": name}
