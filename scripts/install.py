#!/usr/bin/env python3
"""Link one canonical skill folder into both Codex and Claude Code's skill directories."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def install_link(destination: Path, *, dry_run: bool) -> str:
    if destination.exists() or destination.is_symlink():
        if destination.resolve() == ROOT:
            return f"already installed: {destination}"
        raise RuntimeError(f"Destination exists and points elsewhere; refusing to overwrite: {destination}")
    if dry_run:
        return f"would link: {destination} -> {ROOT}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        destination.symlink_to(ROOT, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        # Junctions do not require Developer Mode, unlike Windows symlinks.
        run = subprocess.run(["cmd", "/c", "mklink", "/J", str(destination), str(ROOT)],
                             capture_output=True, text=True, check=False)
        if run.returncode or not destination.exists():
            raise RuntimeError(f"Windows link/junction creation failed: {run.stdout} {run.stderr}")
    return f"installed: {destination} -> {ROOT}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Install shared ai-app-maintainer skill links; never copy runtime history")
    parser.add_argument("--agent", choices=("codex", "claude", "both"), default="both")
    parser.add_argument("--scope", choices=("user", "project"), default="user")
    parser.add_argument("--project-root", help="Required absolute project folder for --scope project")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.scope == "project":
        if not args.project_root:
            parser.error("--project-root is required with --scope project")
        root = Path(args.project_root).expanduser().resolve(strict=True)
        if not root.is_dir():
            parser.error("--project-root must be a directory")
    else:
        root = Path.home()
    names = ["codex", "claude"] if args.agent == "both" else [args.agent]
    try:
        for name in names:
            directory = ".agents" if name == "codex" else ".claude"
            print(install_link(root / directory / "skills" / ROOT.name, dry_run=args.dry_run))
    except (RuntimeError, OSError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
