"""Filesystem, logging, and policy helpers for ai-app-maintainer (stdlib only)."""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config.json"
REGISTRY = ROOT / "registry.json"
MANAGED = ROOT / "managed-apps"
REPORTS = ROOT / "reports"

DEFAULTS = {
    "engine": "codex",
    "lookback_hours": 24,
    "run_every_hours": 24,
    "auto_fix": True,
    "upgrade_suggestions": True,
    "monitor_days": 5,
    "monitor_check_every_hours": 6,
    "monitor_min_checks": 3,
    "monitor_run_tests": True,
    "min_auto_confidence": 0.90,
    "max_log_files": 40,
    "max_bytes_per_log": 131072,
    "max_total_log_bytes": 786432,
    "agent_timeout_seconds": 900,
    "test_timeout_seconds": 240,
    "max_patch_files": 6,
    "max_patch_bytes": 100000,
    "max_patch_changed_lines": 300,
    "require_tests_for_auto_fix": True,
}
APP_DEFAULTS = {
    "enabled": True,
    "log_globs": ["logs/**/*.log", "logs/**/*.jsonl", "log/**/*.log", "*.log"],
    "test_commands": [],
    "notes": "",
    "auto_fix": None,
    "upgrade_suggestions": None,
    "lookback_hours": None,
    "run_every_hours": None,
    "monitor_days": None,
    "monitor_run_tests": None,
}
EXCLUDED_DIRS = {
    ".git", ".claude", ".agents", ".codex", ".venv", "venv", "node_modules",
    "__pycache__", ".pytest_cache", ".mypy_cache", "dist", "build", ".next",
    "coverage", ".idea", ".vscode", "logs", "log", "tmp", "temp", "cache", ".cache",
    ".ssh", ".aws", ".kube", "secrets", "private", "uploads", "data", "sessions", "certs",
}
EXCLUDED_FILE_PATTERNS = [
    ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "*.sqlite", "*.db",
    "*credentials*", "*secret*", "*.log", "*.jsonl", "AGENTS.md", "*.keystore", "*.jks", "*.p8", "id_rsa*",
]
# Protect high-impact and sensitive files against *unapproved* changes.
RISKY_PATH_PATTERNS = [
    "*auth*", "*permission*", "*payment*", "*billing*", "*migrat*", "*schema*",
    "*security*", "*secret*", "*credential*", "*deploy*", "*infra*", "*terraform*",
    "*dockerfile*", "*workflow*", "*config*", "package.json", "*lock*", "pyproject.toml",
    "requirements*.txt", ".github/*", "*.sql", "*.sh", "*.ps1", "*.bat", "*.cmd",
]
AUTO_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".rb", ".php", ".cs", ".css", ".html"}
TIMESTAMP_RE = re.compile(r"(?P<date>20\d\d[-/]\d\d[-/]\d\d)[ T](?P<time>\d\d:\d\d:\d\d(?:[.,]\d{1,6})?)(?P<offset>Z|[+-]\d\d:?\d\d)?")
KEY_VALUE_SECRET_RE = re.compile(r'(?i)(["\']?(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret|authorization)["\']?\s*[:=]\s*)["\']?([^\s,;"\']+)', re.I)
BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{8,}")


def now() -> datetime:
    return datetime.now(timezone.utc)


def stamp(dt: datetime | None = None) -> str:
    return (dt or now()).astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_time(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return dt.astimezone(timezone.utc)


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=str(path.parent), prefix=".pending-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")


def record(app_id: str, event: str, **fields: Any) -> None:
    payload = {"at": stamp(), "event": event, **fields}
    append_jsonl(app_dir(app_id) / "history.jsonl", payload)
    # Readable high-level chronological history; JSONL is the canonical audit log.
    note = str(fields.get("summary") or fields.get("status") or fields.get("reason") or "")
    note = note.replace("\n", " ")[:240]
    with (app_dir(app_id) / "history.md").open("a", encoding="utf-8") as f:
        f.write(f"- {payload['at']} | **{event}** | {note}\n")


def ensure_initialized() -> None:
    if not CONFIG.exists():
        atomic_json(CONFIG, DEFAULTS)
    if not REGISTRY.exists():
        atomic_json(REGISTRY, {"apps": {}})
    MANAGED.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)


def config() -> dict[str, Any]:
    ensure_initialized()
    value = load_json(CONFIG, {})
    if not isinstance(value, dict):
        raise ValueError("config.json must contain a JSON object")
    merged = {**DEFAULTS, **value}
    if merged["engine"] not in {"codex", "claude"}:
        raise ValueError("engine must be codex or claude")
    for key in ("auto_fix", "upgrade_suggestions", "require_tests_for_auto_fix", "monitor_run_tests"):
        if type(merged[key]) is not bool:
            raise ValueError(f"{key} must be true/false")
    for key in ("lookback_hours", "run_every_hours", "monitor_days", "monitor_check_every_hours", "agent_timeout_seconds", "test_timeout_seconds", "max_log_files", "max_bytes_per_log", "max_total_log_bytes", "max_patch_files", "max_patch_bytes", "max_patch_changed_lines", "monitor_min_checks"):
        if type(merged[key]) not in (int, float) or merged[key] <= 0:
            raise ValueError(f"{key} must be positive")
    if not 0 <= merged["min_auto_confidence"] <= 1:
        raise ValueError("min_auto_confidence must be 0..1")
    return merged


def registry() -> dict[str, Any]:
    ensure_initialized()
    value = load_json(REGISTRY, {"apps": {}})
    if not isinstance(value, dict) or not isinstance(value.get("apps"), dict):
        raise ValueError("registry.json must contain {\"apps\": {...}}")
    return value


def validate_slug(slug: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,48}", slug):
        raise ValueError("App ID: lowercase letters, digits, hyphen (start with a letter), max 49")
    return slug


def app_dir(app_id: str) -> Path:
    return MANAGED / validate_slug(app_id)


def app_settings(app: dict, cfg: dict) -> dict:
    merged = {**cfg, **{k: v for k, v in APP_DEFAULTS.items() if k not in cfg}}
    for k, v in app.items():
        if v is not None:
            merged[k] = v
    return merged


def app_path(app: dict) -> Path:
    path = Path(app["path"]).expanduser().resolve(strict=True)
    if not path.is_dir():
        raise ValueError("App path is not a directory")
    return path


def init_app_dirs(app_id: str) -> None:
    base = app_dir(app_id)
    for name in ("inspections", "findings", "proposals", "fixes", "monitors", "backups"):
        (base / name).mkdir(parents=True, exist_ok=True)
    if not (base / "history.md").exists():
        (base / "history.md").write_text(f"# {app_id} 유지보수 이력\n\n", encoding="utf-8")


def short_hash(value: str, length: int = 12) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def redact(text: str) -> str:
    text = BEARER_RE.sub("Bearer [REDACTED]", text)
    return KEY_VALUE_SECRET_RE.sub(lambda m: m.group(1) + "[REDACTED]", text)


def line_time(text: str) -> datetime | None:
    # JSON lines are common in application logs.
    if text.lstrip().startswith("{"):
        try:
            obj = json.loads(text)
            for field in ("timestamp", "time", "@timestamp", "datetime", "ts"):
                v = obj.get(field)
                if isinstance(v, str):
                    return parse_time(v)
                if isinstance(v, (int, float)) and 946684800 <= v <= 4102444800:
                    return datetime.fromtimestamp(v, tz=timezone.utc)
        except (ValueError, TypeError, AttributeError, OverflowError):
            pass
    match = TIMESTAMP_RE.search(text[:120])
    if match:
        value = (match.group("date").replace("/", "-") + "T" +
                 match.group("time").replace(",", ".") + (match.group("offset") or ""))
        try:
            return parse_time(value)
        except ValueError:
            return None
    return None


def _tail_bytes(path: Path, limit: int) -> str:
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        length = f.tell()
        f.seek(max(0, length - limit))
        data = f.read(limit)
    if length > limit:
        data = data.split(b"\n", 1)[-1]  # avoid first truncated line
    return data.decode("utf-8", errors="replace")


def collect_logs(root: Path, patterns: list[str], lookback_hours: float, limits: dict) -> dict[str, Any]:
    """Bounded, redacted snapshot of recent log records. Unstamped lines are labeled uncertain."""
    cutoff = now() - timedelta(hours=lookback_hours)
    selected: dict[str, Path] = {}
    issues: list[str] = []
    for pattern in patterns:
        if not isinstance(pattern, str) or pattern.startswith(("/", "~")) or ".." in Path(pattern).parts or Path(pattern).is_absolute():
            issues.append(f"Unsafe log glob ignored: {pattern!r}")
            continue
        try:
            for item in root.glob(pattern):
                if item.is_symlink() or not item.is_file():
                    continue
                resolved = item.resolve()
                if not resolved.is_relative_to(root):
                    continue
                selected[str(resolved)] = item
        except (OSError, ValueError) as e:
            issues.append(f"Log pattern {pattern}: {e}")
    paths = sorted(selected.values(), key=lambda p: p.stat().st_mtime, reverse=True)[:int(limits["max_log_files"])]
    records: list[dict[str, Any]] = []
    remaining = int(limits["max_total_log_bytes"])
    verified = unverified = 0
    used_files = []
    for path in paths:
        if remaining <= 0:
            break
        try:
            st = path.stat()
            content = _tail_bytes(path, min(remaining, int(limits["max_bytes_per_log"])))
            remaining -= len(content.encode("utf-8", errors="replace"))
            file_modified = datetime.fromtimestamp(st.st_mtime, timezone.utc)
            # Continuation lines inherit the preceding explicit timestamp in their log entry.
            active_time: datetime | None = None
            active_verified = False
            for line in content.splitlines():
                parsed = line_time(line)
                if parsed is not None:
                    active_time, active_verified = parsed, True
                elif active_time is None:
                    active_time, active_verified = file_modified, False
                if active_time >= cutoff and active_time <= now() + timedelta(minutes=5):
                    normalized = redact(line)[:3000]
                    records.append({"file": str(path.relative_to(root)), "at": stamp(active_time),
                                    "verified_timestamp": active_verified, "text": normalized})
                    if active_verified:
                        verified += 1
                    else:
                        unverified += 1
            used_files.append(str(path.relative_to(root)))
        except (OSError, PermissionError) as e:
            issues.append(f"Cannot read {path.name}: {e.__class__.__name__}")
    # Preserve the last events, avoid unlimited token use.
    if len(records) > 1200:
        records = records[-1200:]
        issues.append("Evidence trimmed to the last 1200 log lines")
    return {"cutoff_utc": stamp(cutoff), "collected_at_utc": stamp(), "files": used_files,
            "records": records, "verified_lines": verified, "unverified_lines": unverified,
            "issues": issues}


def risky_auto_path(rel: str) -> bool:
    name = rel.lower().replace("\\", "/")
    parts = name.split("/")
    if any(p.startswith(".") for p in parts) or Path(name).suffix.lower() not in AUTO_EXTENSIONS:
        return True
    return any(fnmatch.fnmatch(name, pat) or any(fnmatch.fnmatch(p, pat) for p in parts)
               for pat in RISKY_PATH_PATTERNS)


def excluded_file(name: str) -> bool:
    n = name.lower()
    return any(fnmatch.fnmatch(n, pat.lower()) for pat in EXCLUDED_FILE_PATTERNS)


def stage_copy(source: Path, target: Path) -> None:
    """Build restricted temporary source copy. No links, secrets, huge assets, or app logs."""
    target.mkdir(parents=True, exist_ok=True)
    file_count = total_bytes = 0
    for dirname, subdirs, files in os.walk(source, followlinks=False):
        here = Path(dirname)
        relative = here.relative_to(source)
        subdirs[:] = [d for d in subdirs if d not in EXCLUDED_DIRS and not d.startswith(".") and not (here / d).is_symlink()]
        (target / relative).mkdir(parents=True, exist_ok=True)
        for filename in files:
            if excluded_file(filename) or filename.startswith("."):
                continue
            src = here / filename
            if src.is_symlink() or not src.is_file():
                continue
            size = src.stat().st_size
            if size > 5 * 1024 * 1024:
                continue
            file_count += 1
            total_bytes += size
            if file_count > 12000 or total_bytes > 180 * 1024 * 1024:
                raise RuntimeError("Staging size exceeds limits; reduce the app folder or add excludes")
            dest = target / relative / filename
            shutil.copy2(src, dest)


def tree_snapshot(root: Path) -> dict[str, dict[str, Any]]:
    """Paths and hashes including symlink flag, for post-agent change validation."""
    output = {}
    for base, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(base) / d).is_symlink()]
        for name in files:
            path = Path(base) / name
            rel = path.relative_to(root).as_posix()
            if path.is_symlink():
                output[rel] = {"symlink": True}
            elif path.is_file():
                output[rel] = {"sha256": sha_file(path), "size": path.stat().st_size}
    return output


def validate_diff(before: dict, after: dict, auto: bool, cfg: dict) -> list[str]:
    changed = sorted(set(before) | set(after))
    changed = [p for p in changed if before.get(p) != after.get(p)]
    if not changed:
        raise ValueError("AI did not change any source file")
    if len(changed) > int(cfg["max_patch_files"]):
        raise ValueError("Too many changed files")
    size = sum((after.get(p) or {}).get("size", 0) for p in changed)
    if size > int(cfg["max_patch_bytes"]):
        raise ValueError("Changed file content exceeds byte limit")
    for rel in changed:
        if rel not in after:
            raise ValueError(f"File deletions are not automatically applied: {rel}")
        if after[rel].get("symlink"):
            raise ValueError(f"Symlink changes are prohibited: {rel}")
        if excluded_file(Path(rel).name) or any(p.startswith(".") for p in Path(rel).parts):
            raise ValueError(f"Protected path: {rel}")
        if auto and risky_auto_path(rel):
            raise ValueError(f"Critical/unknown file not eligible for auto-fix: {rel}")
    return changed


def copy_atomic(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=str(dst.parent), prefix=".ai-maint-temp-")
    try:
        with os.fdopen(fd, "wb") as out, src.open("rb") as inp:
            shutil.copyfileobj(inp, out)
            out.flush()
            os.fsync(out.fileno())
        if dst.exists():
            shutil.copymode(dst, name)
        os.replace(name, dst)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def check_target_path(root: Path, rel: str) -> Path:
    """Never write through symlink parents or outside the registered app."""
    target = root / rel
    if not target.resolve(strict=False).is_relative_to(root):
        raise RuntimeError(f"Target escaped registered app: {rel}")
    item = root
    for piece in Path(rel).parts:
        item = item / piece
        if item.is_symlink():
            raise RuntimeError(f"Symlink target prohibited: {rel}")
    return target
