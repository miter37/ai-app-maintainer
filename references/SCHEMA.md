# 구조 / 설정 / 이력 형식

## 전역 `config.json`

| 항목 | 기본값 | 의미 |
| --- | --- | --- |
| `engine` | `"codex"` | AI 구독 CLI (`codex` / `claude`) |
| `lookback_hours` | `24` | 로그 분석 기간 (시간) |
| `run_every_hours` | `24` | 일반 점검 목표 간격 |
| `auto_fix` | `true` | 저위험 버그 자동 패치 허용 |
| `upgrade_suggestions` | `true` | 기능·메뉴·UX 제안 탐색 여부. 실행은 승인 필요 |
| `monitor_days` | `5` | 수정 후 집중 관찰 일수 |
| `monitor_check_every_hours` | `6` | 집중 관찰 점검 목표 간격 |
| `monitor_min_checks` | `3` | 근거 있는 관찰 종료를 위한 최소 횟수 |
| `monitor_run_tests` | `true` | 집중 관찰 중 등록된 안전한 테스트 재실행 여부 |
| `min_auto_confidence` | `0.9` | 자동 수정에 요구하는 최소 AI 확신도 (참고 기준일 뿐 검증 대체 불가) |
| `require_tests_for_auto_fix` | `true` | 테스트 없는 자동수정 차단 |
| `max_log_files` | `40` | 분석할 최대 로그 파일 개수 |
| `max_bytes_per_log` | `131072` | 파일당 읽는 최대 바이트 |
| `max_total_log_bytes` | `786432` | 모든 로그 합계의 최대 바이트 |
| `agent_timeout_seconds` | `900` | 한 번 AI 요청 최대 시간 |
| `test_timeout_seconds` | `240` | 각 테스트 최대 시간 |
| `max_patch_files` | `6` | 한 제안의 변경 파일 제한 |
| `max_patch_bytes` | `100000` | 변경 파일 총 바이트 제한 |
| `max_patch_changed_lines` | `300` | diff 변경 줄 수 제한 |

불리언 값은 JSON `true` / `false`이며 스킬 UI는 존재하지 않는다. CLI에서는 `--value on|off`도 허용한다. 전역값과 앱별 재정의 중 앱별 값이 우선한다.

## 앱 등록 `registry.json`

```json
{
  "apps": {
    "billing-api": {
      "path": "/srv/projects/billing-api",
      "enabled": true,
      "log_globs": ["logs/**/*.log", "logs/**/*.jsonl"],
      "test_commands": [["python", "-m", "pytest", "-q"]],
      "notes": "간단한 운영 정보 (비밀번호·토큰 기록 금지)",
      "auto_fix": null,
      "upgrade_suggestions": null,
      "lookback_hours": null,
      "run_every_hours": null,
      "monitor_days": null
    }
  }
}
```

`null`이면 전역 설정을 상속한다. `test_commands`는 셸이 아닌 argv 배열이다. 앱을 제거하려면 사용자가 `registry.json`의 해당 항목을 제거하되 기존 이력 폴더는 삭제하지 않는다.

## 관리 이력

```text
ai-app-maintainer/
├── SKILL.md
├── config.json
├── registry.json
├── scripts/
│   ├── maintainer.py
│   ├── core.py
│   ├── workflow.py
│   ├── agent_bridge.py
│   ├── install.py
│   ├── run_due.sh
│   └── run_due.ps1
├── references/
│   ├── USAGE_KO.md
│   ├── SCHEMA.md
│   ├── SECURITY.md
│   ├── ANALYZE.md
│   └── IMPLEMENT.md
├── managed-apps/
│   └── billing-api/
│       ├── inspections/       # 분석 시점별 익명화 로그 증거/결과/보고서
│       ├── findings/          # 발견된 원인/근거
│       ├── proposals/         # 승인대기, 승인, 거절, 적용 상태
│       ├── fixes/             # 소스 변경 적용/검증 결과
│       ├── monitors/          # 수정 후 며칠간 집중 관찰 상태
│       ├── backups/           # 변경 전 원본 파일 백업
│       ├── status.json        # 마지막 점검 개요
│       ├── history.jsonl      # 정형 감사 이벤트 (정본)
│       ├── history.md         # 가독성 있는 감사 이벤트
│       ├── latest-report.md   # 최신 정기 유지보수 보고
│       └── latest-suggestions.md
└── reports/
    ├── last.md
    ├── billing-api-YYYYMMDD....md
    └── scheduler.log
```

실제 원본 앱 소스는 `registry.json`의 `path` 아래에 두고, 오직 성공한 안전성 검증 후 소스 파일만 반영한다. `backups/`는 스킬 폴더 안에 있고 민감한 소스가 들어갈 수 있으므로 공유/커밋하지 않는다.

## 제안 상태

- `pending_auto`: 자동 수정 후보이지만 아직 검증/적용 전
- `pending_approval`: 위험, 불확실성, 기능/UX 제안 또는 자동 검증 실패로 사용자 승인 필요
- `approved`: 사용자 승인 기록. 실행 전 또는 재시도 대기
- `applied`: 원본 소스에 적용, 검증을 통과함 (서비스 배포는 아님)
- `rejected`: 거절 이력을 저장, 동일 제안 자동 재제안 억제

## 모니터 상태

- `watching`: 집중 관찰 중
- `regression_suspected`: 이전 오류 문자열이 수정 후 로그에서 재발함
- `stable_observed`: 필요한 개수의 타임스탬프 확인된 관찰이 있고 재발 신호를 보지 못함
- `insufficient_evidence`: 기간은 지났으나 확인 가능한 기록 부족
- `needs_review`: 재발 의심 상태가 기간 종료 시점에도 해결되지 않음

정상 종료는 전체 기능의 무결성을 보장하지 않는다.
