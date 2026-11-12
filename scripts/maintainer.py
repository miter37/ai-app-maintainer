#!/usr/bin/env python3
"""AI app maintenance skill CLI (JSON settings and filesystem records; no GUI/server)."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from core import (
    APP_DEFAULTS, CONFIG, DEFAULTS, MANAGED, REGISTRY, ROOT, app_dir, app_path, app_settings,
    atomic_json, collect_logs, config, ensure_initialized, init_app_dirs, load_json,
    record, registry, validate_slug,
)
from workflow import apply_preapproved, decide, eligible_to_run, read_monitors, rid, run_one, suggest_one


class Lock:
    """Fail closed on overlapping scheduled cycles. Remove stale lock manually after checking processes."""

    def __enter__(self):
        self.path = ROOT / ".maintainer.lock"
        try:
            fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as e:
            raise RuntimeError(f"Another maintenance process may be active: {self.path}. Check processes before removing lock.") from e
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(f"pid={os.getpid()}\n")
        return self

    def __exit__(self, *_):
        self.path.unlink(missing_ok=True)


def render(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


HELP_TOPICS = {
    "overview": """ai-app-maintainer | AI 앱 유지보수 스킬 (GUI 없음)

[처음 시작] 스킬 폴더는 Codex와 Claude Code에서 공통으로 사용합니다.
  python scripts/maintainer.py help 등록
  python scripts/maintainer.py doctor
  python scripts/maintainer.py list

[기본 사용]
  python scripts/maintainer.py add --app my-app --path /absolute/path/to/app --log 'logs/**/*.log' --test 'python -m pytest -q'
  python scripts/maintainer.py run --app my-app
  python scripts/maintainer.py run --due
  python scripts/maintainer.py suggest --app my-app
  python scripts/maintainer.py pending --app my-app
  python scripts/maintainer.py status --app my-app
  python scripts/maintainer.py report --app my-app

[자연어 호출]
  Codex: $ai-app-maintainer 사용법 알려줘
  Claude Code: /ai-app-maintainer help
  '유지보수스킬 어떻게 사용해?', '앱 폴더 등록은?', '업그레이드 제안은 어떻게 해?'

[자세히] help 등록 | 점검 | 제안 | 승인 | 설정 | 집중관찰 | 일정 | 설치 | mcp
""",
    "등록": """앱 폴더 등록
  python scripts/maintainer.py add --app billing-api --path '/절대경로/앱' \
      --log 'logs/**/*.log' --log 'logs/**/*.jsonl' \
      --test 'python -m pytest -q'
  python scripts/maintainer.py list
- --app은 영문 소문자·숫자·하이픈 식별자. --path는 존재하는 실제 폴더.
- --log는 앱 폴더 기준 glob이며 반복 지정 가능.
- --test는 안전한 테스트/스모크 명령이며 반복 지정 가능(셸 리다이렉션/파이프 불가).
- 자동 수정은 검증 테스트가 없으면 승인 대기 처리됩니다.
- 등록 내용은 registry.json에 저장. 앱별 기록은 managed-apps/<앱ID>/에 저장.
""",
    "점검": """유지보수 실행 / 로그 점검
  python scripts/maintainer.py inspect --app billing-api
  python scripts/maintainer.py run --app billing-api
  python scripts/maintainer.py run --all
  python scripts/maintainer.py run --due
  python scripts/maintainer.py run --app billing-api --no-agent
- inspect는 최근 로그만 읽습니다. run은 AI 분석·자동 버그수정·승인대기 생성·후속관찰을 포함합니다.
- --due는 마지막 실행시각과 수정 후 집중관찰 주기를 고려합니다.
- 최초 점검 전에 doctor로 AI CLI 인증/설치 상태를 확인하세요.
""",
    "제안": """업그레이드 / 기능·메뉴·UX 개선 제안
  python scripts/maintainer.py suggest --app billing-api
  python scripts/maintainer.py suggest --all
  python scripts/maintainer.py config --key upgrade_suggestions --value off
  python scripts/maintainer.py set-app --app billing-api --key upgrade_suggestions --value on
- 기능추가/메뉴 개편/UX 개선은 항상 승인 대기. 자동 구현 금지.
- '업그레이드 제안은 어떻게 해?' 같은 질문에는 사용법만 설명합니다.
- 'billing-api 업그레이드 제안해' 같은 실행 요청에서만 suggest를 수행합니다.
- 결과는 managed-apps/<앱ID>/latest-suggestions.md, proposals/*.json에 저장됩니다.
""",
    "승인": """승인 대기, 적용 및 거절
  python scripts/maintainer.py pending --app billing-api
  python scripts/maintainer.py approve --app billing-api --id <제안ID>
  python scripts/maintainer.py approve --app billing-api --id <제안ID> --no-apply
  python scripts/maintainer.py reject --app billing-api --id <제안ID>
- 승인 대상의 앱 ID·제안 ID·변경 범위를 확인한 뒤 명시적으로 승인합니다.
- approve는 승인된 제안을 임시 작업본에서 구현하고 테스트 후 원본 소스에 적용합니다.
- 테스트 미설정 시에도 위험을 감수하고 승인하려면 --allow-unverified를 명시해야 합니다.
- 서비스 배포·재시작·DB 마이그레이션은 자동으로 수행하지 않습니다.
""",
    "설정": """GUI 없이 JSON/CLI로 ON/OFF 저장
  python scripts/maintainer.py config
  python scripts/maintainer.py config --key auto_fix --value off
  python scripts/maintainer.py config --key upgrade_suggestions --value on
  python scripts/maintainer.py config --key lookback_hours --value 48
  python scripts/maintainer.py config --key engine --value claude
  python scripts/maintainer.py set-app --app billing-api --key auto_fix --value off
- config.json은 전역값, registry.json의 앱별 값은 우선 적용됩니다.
- auto_fix는 버그 수정만 제어합니다. 기능·UX 제안은 항상 승인 필요.
""",
    "집중관찰": """수정 후 특별 집중관찰
  python scripts/maintainer.py config --key monitor_days --value 5
  python scripts/maintainer.py config --key monitor_check_every_hours --value 6
  python scripts/maintainer.py status --app billing-api
  python scripts/maintainer.py history --app billing-api
- 수정 성공 시 5일 관찰 시작. 기본 6시간마다 점검 대상이 됩니다.
- 이전 오류의 특정 로그 문자열 재발, 새 오류, 기능 동작 이상을 집중 관찰합니다.
- 오류가 보이지 않는다고 정상 작동을 확정하지 않으며 로그 데이터가 부족하면 미확인으로 남깁니다.
- 후속 관찰 자동 주기를 실제로 실행하려면 OS 스케줄러에서 run --due를 호출해야 합니다.
""",
    "일정": """예약 자동 점검(별도 GUI 없음)
  Linux/macOS: 매시간 cron에서 scripts/run_due.sh 실행
  Windows: 작업 스케줄러에서 scripts/run_due.ps1 실행
- run --due는 앱별 기본 24시간/관찰 중 6시간 간격을 내부적으로 계산합니다.
- 스킬 자체는 백그라운드 서비스가 아니며 스케줄러 연결 전에는 자동 실행되지 않습니다.
- 절대경로 실행법은 references/USAGE_KO.md 참조.
""",
    "mcp": """Hermes Agent / OpenClaw 등 상주봇용 MCP (로컬 STDIO, GUI 없음)
  python scripts/mcp_server.py --check
  python scripts/maintainer.py config --key mcp_allow_execution --value off
  python scripts/maintainer.py config --key mcp_allow_registration --value on
  python scripts/maintainer.py config --key mcp_allow_settings_changes --value on
- 실행 중인 에이전트에 로컬 STDIO MCP 서버로 scripts/mcp_server.py를 등록합니다.
- Hermes: ~/.hermes/config.yaml 의 mcp_servers 설정.
- OpenClaw: openclaw mcp add ai-app-maintainer --command python3 --arg /절대경로/scripts/mcp_server.py
- MCP에는 승인 생성 기능이 없습니다. 사람은 신뢰된 로컬 CLI에서 approve --no-apply.
- auto_fix=true이면 MCP를 통한 유지보수 실행이 원본 버그를 수정할 수 있습니다.
- 상주봇 cron과 서버 설치 및 보안 상세: references/MCP.md
""",
    "설치": """Codex / Claude Code 스킬 설치
  python scripts/install.py --agent both --scope user
  python scripts/maintainer.py doctor
- Codex: ~/.agents/skills/ai-app-maintainer/SKILL.md
- Claude Code: ~/.claude/skills/ai-app-maintainer/SKILL.md
- 동일한 원본 폴더에 링크하므로 앱별 관리 기록을 하나만 유지합니다.
- 보안상 CLI 인증과 스케줄러는 사용자의 환경에서 별도로 설정해야 합니다.
""",
}


def show_help(topic_parts):
    topic = " ".join(topic_parts).strip().lower()
    aliases = {
        "help": "overview", "사용법": "overview", "how": "overview", "usage": "overview",
        "register": "등록", "add": "등록", "앱 등록": "등록", "등록": "등록",
        "run": "점검", "inspect": "점검", "유지보수": "점검", "점검": "점검",
        "suggest": "제안", "upgrade": "제안", "업그레이드": "제안", "업그레이드 제안": "제안", "제안": "제안",
        "approve": "승인", "reject": "승인", "pending": "승인", "승인": "승인",
        "config": "설정", "setting": "설정", "on/off": "설정", "설정": "설정",
        "monitor": "집중관찰", "watch": "집중관찰", "관찰": "집중관찰", "집중관찰": "집중관찰",
        "schedule": "일정", "cron": "일정", "예약": "일정", "일정": "일정",
        "install": "설치", "설치": "설치",
        "mcp": "mcp", "hermes": "mcp", "openclaw": "mcp", "상주봇": "mcp",
    }
    selected = aliases.get(topic, "overview")
    if topic and selected == "overview":
        if any(w in topic for w in ("업그레이드", "제안", "메뉴", "기능추가")):
            selected = "제안"
        elif any(w in topic for w in ("등록", "폴더", "추가")):
            selected = "등록"
        elif any(w in topic for w in ("승인", "허가", "거절")):
            selected = "승인"
        elif any(w in topic for w in ("관찰", "모니터")):
            selected = "집중관찰"
        elif any(w in topic for w in ("mcp", "hermes", "openclaw", "상주봇")):
            selected = "mcp"
        elif any(w in topic for w in ("설정", "스위치", "끄", "켜")):
            selected = "설정"
    print(HELP_TOPICS[selected].strip())


def add(args):
    app_id = validate_slug(args.app)
    p = Path(args.path).expanduser().resolve(strict=True)
    if not p.is_dir():
        raise ValueError("Registered path must be a directory")
    if p.is_relative_to(ROOT) or ROOT.is_relative_to(p):
        raise ValueError("The app folder and skill folder must be separate (no parent/child nesting)")
    reg = registry()
    if app_id in reg["apps"]:
        raise ValueError(f"{app_id} is already registered. Edit with `set-app` or registry.json")
    for other_id, other in reg["apps"].items():
        if Path(other["path"]).resolve() == p:
            raise ValueError(f"That app path is already registered as {other_id}")
    tests = []
    if args.test:
        from workflow import command_list
        tests = [command_list(x) for x in args.test]
    new = {**APP_DEFAULTS, "path": str(p), "notes": args.notes or "", "test_commands": tests}
    if args.log:
        new["log_globs"] = args.log
    reg["apps"][app_id] = new
    atomic_json(REGISTRY, reg)
    init_app_dirs(app_id)
    record(app_id, "app_registered", summary=f"Registered {p}")
    render({"registered": app_id, "path": str(p), "tests": tests, "logs": new["log_globs"]})


def convert_global(key: str, value: str):
    if key not in DEFAULTS:
        raise ValueError(f"Unknown setting: {key}. Available: {', '.join(DEFAULTS)}")
    expected = DEFAULTS[key]
    if type(expected) is bool:
        if value.lower() not in ("true", "false", "on", "off", "1", "0"):
            raise ValueError("Boolean needs on/off/true/false/1/0")
        return value.lower() in ("true", "on", "1")
    if type(expected) is int:
        return int(value)
    if type(expected) is float:
        return float(value)
    return value


def global_set(args):
    if not args.key:
        render(config())
        return
    cfg = config()
    value = convert_global(args.key, args.value)
    new = {**cfg, args.key: value}
    atomic_json(CONFIG, new)
    try:
        config()  # validate
    except Exception:
        atomic_json(CONFIG, cfg)
        raise
    render({"key": args.key, "value": value})


def app_set(args):
    reg = registry()
    app = reg["apps"].get(args.app)
    if app is None:
        raise ValueError("Unknown app")
    allowed = {"enabled", "auto_fix", "upgrade_suggestions", "lookback_hours", "run_every_hours", "monitor_days", "monitor_check_every_hours", "monitor_run_tests", "notes"}
    if args.key not in allowed:
        raise ValueError(f"Allowed app overrides: {', '.join(sorted(allowed))}. Edit registry.json for log_globs/test_commands")
    if args.value.lower() == "inherit" and args.key in {"auto_fix", "upgrade_suggestions", "lookback_hours", "run_every_hours", "monitor_days", "monitor_check_every_hours", "monitor_run_tests"}:
        value = None
    elif args.key == "enabled" or args.key in {"auto_fix", "upgrade_suggestions", "monitor_run_tests"}:
        value = convert_global("auto_fix", args.value)
    elif args.key in {"lookback_hours", "run_every_hours", "monitor_days", "monitor_check_every_hours"}:
        value = float(args.value)
        if value <= 0:
            raise ValueError("Hours/days must be positive")
    else:
        value = args.value
    app[args.key] = value
    atomic_json(REGISTRY, reg)
    record(args.app, "app_setting_changed", summary=f"{args.key}={value}")
    render({"app": args.app, "key": args.key, "value": value})


def inspect(args):
    reg = registry()
    app = reg["apps"].get(args.app)
    if app is None:
        raise ValueError("Unknown app")
    settings = app_settings(app, config())
    logs = collect_logs(app_path(app), settings["log_globs"], settings["lookback_hours"], settings)
    if args.save:
        dest = app_dir(args.app) / "inspections" / f"manual-{rid()}"
        dest.mkdir(parents=True, exist_ok=False)
        atomic_json(dest / "evidence.json", logs)
        logs["saved_to"] = str(dest / "evidence.json")
    # Show only a small preview; saved copy contains full redacted evidence.
    logs["records_preview"] = logs.pop("records")[-10:]
    render(logs)


def do_run(args):
    reg = registry()["apps"]
    if args.app:
        if args.app not in reg:
            raise ValueError("Unknown app")
        names = [args.app]
    else:
        names = sorted(reg)
    results = []
    for name in names:
        if not reg[name].get("enabled", True):
            results.append({"app": name, "status": "disabled"})
            continue
        settings = app_settings(reg[name], config())
        if args.due and not eligible_to_run(name, settings):
            results.append({"app": name, "status": "not_due"})
            continue
        try:
            results.append(run_one(name, agent=not args.no_agent))
        except Exception as e:
            results.append({"app": name, "status": "failed", "error": str(e)[:1200]})
            init_app_dirs(name)
            record(name, "inspection_error", summary=str(e)[:500])
    render(results)
    if any(x.get("status") == "failed" or x.get("errors") for x in results):
        return 2
    return 0


def do_suggest(args):
    apps = registry()["apps"]
    names = [args.app] if args.app else sorted(apps)
    if args.app and args.app not in apps:
        raise ValueError(f"Unknown app: {args.app}")
    result = []
    for name in names:
        try:
            result.append(suggest_one(name))
        except Exception as e:
            result.append({"app": name, "status": "failed", "error": str(e)[:900]})
            init_app_dirs(name)
            record(name, "suggestion_error", summary=str(e)[:500])
    render(result)
    return 2 if any(x["status"] == "failed" for x in result) else 0


def pending(args):
    names = [args.app] if args.app else sorted(registry()["apps"])
    result = []
    for name in names:
        validate_slug(name)
        for path in sorted((app_dir(name) / "proposals").glob("*.json")):
            p = load_json(path)
            if p.get("status") not in ("applied", "rejected"):
                result.append({k: p.get(k) for k in ("id", "title", "kind", "risk", "confidence", "status", "reason", "last_error", "first_seen_at")}
                              | {"app": name})
    render(result)


def status(args):
    reg = registry()["apps"]
    names = [args.app] if args.app else sorted(reg)
    result = []
    for name in names:
        state = load_json(app_dir(name) / "status.json", {})
        monitors = read_monitors(name)
        result.append({"app": name, "path": reg.get(name, {}).get("path"), "enabled": reg.get(name, {}).get("enabled"),
                       "state": state, "monitors": [
                           {k: m.get(k) for k in ("fix_id", "title", "status", "until_at", "observation_count", "verified_observation_count", "last_checked_at")}
                           for m in monitors]})
    render(result)


def history(args):
    history_path = app_dir(args.app) / "history.jsonl"
    if not history_path.exists():
        render([])
        return
    lines = history_path.read_text(encoding="utf-8").splitlines()
    render([json.loads(line) for line in lines[-args.limit:]])


def doctor():
    cfg = config()
    result = {"skill_folder": str(ROOT), "python": sys.version.split()[0], "engine": cfg["engine"],
              "codex": shutil.which("codex"), "claude": shutil.which("claude"),
              "registered_apps": len(registry()["apps"]), "has_gui": False,
              "scheduler": "NOT INSTALLED: configure cron, launchd, or Windows Task Scheduler yourself"}
    if result[cfg["engine"]] is None:
        result["warning"] = f"{cfg['engine']} is not on PATH; inspect works but AI analysis/fixes do not"
    render(result)


def build_parser():
    p = argparse.ArgumentParser(description="Local AI app maintenance skill. Stores all state within this folder.")
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("help", help="한국어 사용법 및 명령별 도움말 (help 등록/점검/제안/승인/설정/집중관찰/일정/설치/mcp)")
    c.add_argument("topic", nargs="*", help="질문 또는 주제")
    sub.add_parser("init", help="Initialize config, registry and history folders")
    sub.add_parser("doctor", help="Check basic CLI readiness; does not log into AI provider")
    c = sub.add_parser("add", help="Register app root, log globs and smoke/test commands")
    c.add_argument("--app", required=True, help="App ID, e.g. billing-api")
    c.add_argument("--path", required=True)
    c.add_argument("--log", action="append", help="Log glob relative to app root; can repeat")
    c.add_argument("--test", action="append", help='Test command, e.g. "python -m unittest discover -s tests"; can repeat')
    c.add_argument("--notes", default="")
    c = sub.add_parser("config", help="View or change global JSON settings")
    c.add_argument("--key")
    c.add_argument("--value")
    c = sub.add_parser("set-app", help="Set app-level bool or numeric override")
    c.add_argument("--app", required=True)
    c.add_argument("--key", required=True)
    c.add_argument("--value", required=True)
    sub.add_parser("list", help="List registered apps")
    c = sub.add_parser("inspect", help="Collect recent logs without AI or source edits")
    c.add_argument("--app", required=True)
    c.add_argument("--save", action="store_true")
    c = sub.add_parser("run", help="Run log analysis, approvals queue, auto fixes and monitoring")
    g = c.add_mutually_exclusive_group(required=True)
    g.add_argument("--app")
    g.add_argument("--all", action="store_true")
    g.add_argument("--due", action="store_true", help="Only enabled apps due; shorter cadence for recent fixes")
    c.add_argument("--no-agent", action="store_true", help="Collect evidence and monitor only, no AI calls or fixes")
    c = sub.add_parser("suggest", help="Generate feature/menu/UX upgrade proposals ONLY; never auto-apply")
    g = c.add_mutually_exclusive_group(required=True)
    g.add_argument("--app", help="Registered app ID")
    g.add_argument("--all", action="store_true")
    c = sub.add_parser("pending", help="Show proposals awaiting approval or retry")
    c.add_argument("--app")
    c = sub.add_parser("approve", help="Explicitly authorize one proposal; implement unless --no-apply")
    c.add_argument("--app", required=True)
    c.add_argument("--id", required=True)
    c.add_argument("--no-apply", action="store_true")
    c.add_argument("--allow-unverified", action="store_true", help="Explicitly accept no configured tests, for this approval only")
    c = sub.add_parser("apply-approved", help="Apply an already human-approved proposal (never creates approval)")
    c.add_argument("--app", required=True)
    c.add_argument("--id", required=True)
    c = sub.add_parser("reject", help="Reject and remember a proposal")
    c.add_argument("--app", required=True)
    c.add_argument("--id", required=True)
    c = sub.add_parser("status", help="Display latest result and all post-fix watches")
    c.add_argument("--app")
    c = sub.add_parser("history", help="Display recent audit events for one app")
    c.add_argument("--app", required=True)
    c.add_argument("--limit", type=int, default=30)
    c = sub.add_parser("report", help="Print latest Markdown report")
    c.add_argument("--app")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "help":
            show_help(args.topic)
            return 0
        ensure_initialized()
        if args.command == "init":
            render({"config": str(CONFIG), "registry": str(REGISTRY), "managed": str(MANAGED)})
        elif args.command == "doctor":
            doctor()
        elif args.command == "config":
            if args.key and args.value is None:
                raise ValueError("--value required with --key")
            with Lock() if args.key else _NoLock():
                global_set(args)
        elif args.command == "add":
            with Lock():
                add(args)
        elif args.command == "set-app":
            with Lock():
                app_set(args)
        elif args.command == "list":
            render(registry()["apps"])
        elif args.command == "inspect":
            inspect(args)
        elif args.command == "run":
            with Lock():
                return do_run(args)
        elif args.command == "suggest":
            with Lock():
                return do_suggest(args)
        elif args.command == "pending":
            pending(args)
        elif args.command == "approve":
            with Lock():
                render(decide(args.app, args.id, True, apply=not args.no_apply,
                              allow_unverified=args.allow_unverified))
        elif args.command == "apply-approved":
            with Lock():
                render(apply_preapproved(args.app, args.id))
        elif args.command == "reject":
            with Lock():
                render(decide(args.app, args.id, False))
        elif args.command == "status":
            status(args)
        elif args.command == "history":
            history(args)
        elif args.command == "report":
            path = (app_dir(args.app) / "latest-report.md") if args.app else (ROOT / "reports" / "last.md")
            print(path.read_text(encoding="utf-8") if path.exists() else "No report yet")
        else:
            raise ValueError("Unknown command")
        return 0
    except (RuntimeError, ValueError, OSError, KeyError, json.JSONDecodeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


class _NoLock:
    def __enter__(self):
        return self
    def __exit__(self, *_):
        pass


if __name__ == "__main__":
    sys.exit(main())
