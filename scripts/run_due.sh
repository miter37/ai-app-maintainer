#!/usr/bin/env bash
set -euo pipefail
SKILL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$SKILL_ROOT/reports"
python3 "$SKILL_ROOT/scripts/maintainer.py" run --due >> "$SKILL_ROOT/reports/scheduler.log" 2>&1
