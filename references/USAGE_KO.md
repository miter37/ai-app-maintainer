# ai-app-maintainer 한국어 사용 설명서

> 스킬명: **`ai-app-maintainer`**. 별도 앱/GUI가 아닌 `SKILL.md`와 Python 스크립트, `config.json`, `registry.json`, 앱별 기록으로 이루어진 로컬 유지보수 스킬입니다.

## 1. 최초 설치

**필요한 것:** Python 3.10 이상, 로컬 Codex CLI 또는 Claude Code CLI, 실제로 접근 가능한 앱 소스 폴더, 앱이 남기는 로그 폴더. 업그레이드 자동 적용을 원하면 앱별로 재실행 가능한 **안전한 테스트/헬스체크 명령**을 준비합니다.

압축 해제 후 **영구적인 위치**에 `ai-app-maintainer` 폴더를 놓습니다. 동일 스킬을 두 AI 도구에서 공유하려면 스킬을 두 개 복사하지 말고 **원본 폴더 하나에 심볼릭 링크(Windows에서는 junction)를 두 곳 생성**합니다.

```bash
# ai-app-maintainer 폴더에서
python3 scripts/install.py --agent both --scope user
python3 scripts/maintainer.py doctor
```

- Codex 사용자 전역 스킬: `~/.agents/skills/ai-app-maintainer/`
- Claude Code 사용자 전역 스킬: `~/.claude/skills/ai-app-maintainer/`
- 리포지터리 스코프를 원하면 `python3 scripts/install.py --agent both --scope project --project-root '/absolute/path/to/repo'`를 사용합니다.
- 기존 동명의 파일을 덮어쓰지 않으며, 설치는 관리자 권한이 필요한 환경에서 실패할 수 있습니다. Windows에서는 `py -3`를 사용합니다.

AI CLI 인증은 따로 한 번 진행합니다. 예를 들어 `codex login` 또는 `claude auth login`을 해당 CLI의 안내에 따라 실행합니다. 구독 로그인·사용 한도·과금 방식은 각 CLI의 현재 인증 상태에 달려 있습니다. API 키 환경 변수가 별도 결제를 유발하는 경로로 쓰이지 않는지 확인하세요. 이 스킬은 API 키를 생성·저장하지 않습니다.

## 2. 자연어로 사용하기

Codex에서 `$ai-app-maintainer help`, Claude Code에서 `/ai-app-maintainer help`를 입력할 수 있습니다. 자동 호출은 도구가 스킬을 인식할 때 가능하지만 중요 작업은 명시 호출을 권장합니다.

| 자연어 예 | 반응 |
| --- | --- |
| `유지보수스킬 사용법 알려줘` | 설정 및 사용법 안내. 수정 없음 |
| `유지보수스킬 앱 등록하는 법` | `add` 사용 예제 안내. 수정 없음 |
| `업그레이드 제안은 어떻게 해?` | 제안 기능 설명. 스캔하지 않음 |
| `billing-api 폴더를 등록해` | 경로를 확인하고 등록 |
| `billing-api 유지보수 점검해` | 최근 로그 점검, 자동 수정 정책 적용 |
| `billing-api 기능이나 메뉴 개선할 점 제안해` | 신규 제안만 작성. 승인 전 구현 금지 |
| `billing-api 제안 a1b2c3 승인해, 구현해` | 특정 제안의 승인 처리 및 안전성 검증 적용 |
| `며칠 전에 고친 것 잘 작동하나?` | 모니터 기록, 최근 로그, 검증 결과 확인 |

**질문과 지시를 구분합니다.** "어떻게 해?"는 도움말, "해줘"는 명령입니다. 승인에 필요한 앱 ID·제안 ID가 모호하면 승인하지 않고 확인합니다.

## 3. 앱 등록

```bash
python3 scripts/maintainer.py add \
  --app billing-api \
  --path '/srv/projects/billing-api' \
  --log 'logs/**/*.log' \
  --log 'logs/**/*.jsonl' \
  --test 'python -m pytest -q'
python3 scripts/maintainer.py list
```

- `--app`은 앱별 기록 폴더명이므로 고유하고 변하지 않는 영문 식별자입니다.
- `--path`는 **앱 원본 폴더의 절대경로**. 스킬 폴더 내부에 앱을 넣지 않습니다.
- `--log`는 앱 폴더 기준 상대경로 glob. 등록 후에도 `registry.json`에서 수정할 수 있습니다.
- `--test`는 앱을 중단/배포/DB수정/실제 사용자 데이터를 변경하지 않는 검증 명령만 등록합니다. 중복 지정 가능. 공백 분리된 단일 명령이며 셸 파이프/리다이렉션은 지원하지 않습니다.
- 원본 앱이 테스트로 인해 변경될 수 있으므로 실제 운영 서비스에서는 별도의 검증 환경을 권장합니다.

로그 경로가 빠진 경우 등록 당시 기본 glob(`logs/**/*.log`, `logs/**/*.jsonl`, `log/**/*.log`, `*.log`)을 사용합니다. 감지되지 않으면 `inspect`에서 확인 후 수정하세요.

## 4. 점검과 자동 보완

```bash
python3 scripts/maintainer.py inspect --app billing-api
python3 scripts/maintainer.py run --app billing-api
python3 scripts/maintainer.py run --all
python3 scripts/maintainer.py run --due
```

- `inspect`: 최근 로그 수집·기간·비식별화 미리보기만. 앱 소스 수정 없음.
- `run --app`: 즉시 AI 진단을 수행. 명확한 저위험 버그에 한하여 자동 수정 설정이 ON이고 검증 조건이 갖춰지면 임시 복사본에서 패치를 만들고 테스트, 원본 백업, 원본 적용, 재검증합니다.
- 자동 수정이 OFF이거나 위험·불확실·테스트 미설정인 문제는 `pending`에 저장합니다.
- 앱의 실행 중인 프로세스에는 **자동 배포나 재시작을 하지 않습니다.** 파일 수정만으로 실제 실행 서비스가 갱신되는지는 앱 구성에 달려 있습니다.

## 5. 업그레이드 제안: 기본 ON, 무조건 승인 후 구현

```bash
python3 scripts/maintainer.py suggest --app billing-api
python3 scripts/maintainer.py suggest --all
python3 scripts/maintainer.py pending --app billing-api
```

앱의 소스와 최근 로그를 바탕으로 새로운 기능·메뉴 구조·사용성 개선 가능성을 조사하고 `managed-apps/billing-api/latest-suggestions.md`와 `proposals/<제안ID>.json`에 저장합니다. **`suggest`는 구현하지 않습니다.** 일반 `run`에서 발견한 기능/UX 아이디어도 승인 대기입니다. 근거가 부족하면 제안을 억지로 만들지 않습니다.

```bash
# 전역 기능 제안 ON/OFF
python3 scripts/maintainer.py config --key upgrade_suggestions --value off
python3 scripts/maintainer.py config --key upgrade_suggestions --value on
# 앱별 별도 설정
python3 scripts/maintainer.py set-app --app billing-api --key upgrade_suggestions --value off
```

## 6. 중요 변경 승인/거절

```bash
python3 scripts/maintainer.py pending --app billing-api
python3 scripts/maintainer.py approve --app billing-api --id a1b2c3d4e5f678
python3 scripts/maintainer.py reject --app billing-api --id a1b2c3d4e5f678
```

승인 전 제안서의 근거·변경 범위·위험도를 보고합니다. 사용자에게 **"구현할까요?"**라고 묻고, 명시적 승인에 해당하는 한 개의 ID만 실행합니다.

- 승인 시 구현 전 테스트·파일 수정 범위 검증, 백업, 사후 테스트 절차가 있습니다.
- 테스트가 없으면 기본적으로 적용하지 않으며, 위험을 이해한 특정 승인에서만 `--allow-unverified` 선택 가능합니다.
- 승인은 기록하되 실행을 늦추려면 `approve --no-apply`. 추후 `run`에서 승인된 작업을 시도합니다.
- 실패하면 미적용 이유를 기록합니다. 원본 적용 도중 실패하면 파일 백업을 사용해 복구합니다. 외부 데이터/운영상태까지 자동 롤백하는 것은 아닙니다.

## 7. 최근 수정의 집중 관찰

```bash
python3 scripts/maintainer.py config --key monitor_days --value 5
python3 scripts/maintainer.py config --key monitor_check_every_hours --value 6
python3 scripts/maintainer.py status --app billing-api
python3 scripts/maintainer.py history --app billing-api
```

등록된 안전한 테스트 명령이 있으면 집중 관찰 중 기본적으로 다시 실행하며(`monitor_run_tests=true`), 그 결과도 기록합니다. 테스트 실행이 반복되어도 문제가 없는지 반드시 확인하세요.

모든 성공한 원본 수정은 `monitors/<수정ID>.json`을 만들고 기본 **5일** 동안 더 자주 확인합니다. 수정 전의 고유 오류 문자열을 추적하고, 타임스탬프가 확인된 사후 로그를 관찰하며, 재발 신호 발견 시 `regression_suspected`로 표시합니다. 일정 수 이상의 근거가 없으면 `insufficient_evidence`로 남길 수 있습니다. 이 기록은 실제 서비스가 배포되었다는 증명이 아닙니다.

## 8. 정기 실행 — 운영체제 스케줄러를 사용

스킬 자체는 상주하지 않습니다. `run --due`가 앱별 `run_every_hours`(기본 24시간)와 수정 후 `monitor_check_every_hours`(기본 6시간)를 판단하므로 **운영체제에서 매시간 이 스크립트를 호출**하면 됩니다.

Linux/macOS의 cron 항목 예시 (절대경로로 교체):

```cron
0 * * * * /home/you/skills/ai-app-maintainer/scripts/run_due.sh
```

Windows 작업 스케줄러: 매시간 반복되는 작업을 만들고 PowerShell을 시작 프로그램으로 지정합니다. 인수 예:

```powershell
-NoProfile -File "C:\Users\You\Skills\ai-app-maintainer\scripts\run_due.ps1"
```

스케줄러 프로세스에서도 AI CLI 로그인/실행 권한 및 PATH가 준비되어야 합니다. OS 로그인·절전·구독 사용 한도에 따라 예약 작업이 실행되지 않을 수 있습니다. 예약 실행 실패는 `reports/scheduler.log`와 앱별 이력으로 확인합니다. 알림 전송/대화창은 구현하지 않습니다. 승인 요청은 `pending`, `report`를 통해 확인합니다.

## 9. 설정·리포트·진단

```bash
python3 scripts/maintainer.py config
python3 scripts/maintainer.py config --key auto_fix --value off
python3 scripts/maintainer.py config --key lookback_hours --value 48
python3 scripts/maintainer.py config --key run_every_hours --value 12
python3 scripts/maintainer.py config --key engine --value claude
python3 scripts/maintainer.py set-app --app billing-api --key auto_fix --value off
python3 scripts/maintainer.py status --app billing-api
python3 scripts/maintainer.py report --app billing-api
python3 scripts/maintainer.py doctor
```

- 전역 JSON: `config.json` / 관리 앱 목록·앱별 재정의: `registry.json`.
- 이력: `managed-apps/<앱ID>/history.jsonl`와 `history.md`.
- 점검/발견/개선/백업: 동일 앱별 폴더 아래 각각 저장.
- 전체 실행 결과 중 마지막 보고서: `reports/last.md`.
- AI 없이 로그만 확인하려면 `run --app billing-api --no-agent`.
- 사용법만 필요할 때는 `python3 scripts/maintainer.py help` 또는 `help 업그레이드 제안`.

## 10. 테스트 및 제약

```bash
python3 -m unittest discover -s tests -v
```

CLI와 테스트는 Python 표준 라이브러리만 사용하지만 실제 AI 진단은 해당 CLI가 설치·인증되어 있고 실행 환경에서 정상 동작해야 합니다. 자동 수정은 소스 파일을 바꾸므로 중요한 앱은 백업 및 별도 테스트 환경에서 먼저 검증하세요. 로그 비식별화는 최선형이며 비밀값 완전 검출을 보장하지 않습니다. 자세한 내용은 `references/SECURITY.md` 참고.

## 11. Hermes Agent·OpenClaw 상주봇에서 MCP로 사용하기

기존 스킬·CLI에 더해 로컬 STDIO MCP 서버를 사용할 수 있습니다. 웹/GUI/데몬이나 추가 API 요금제를 만들지 않으며, Python 표준 라이브러리만 사용합니다.

```bash
python3 scripts/mcp_server.py --check
python3 scripts/maintainer.py help mcp
```

- Hermes: `~/.hermes/config.yaml`의 `mcp_servers`에 `python3` + `scripts/mcp_server.py` 절대경로를 등록.
- OpenClaw: `openclaw mcp add ai-app-maintainer --command python3 --arg /절대경로/scripts/mcp_server.py`
- 상주봇의 cron에서 `run_maintenance`를 due-only로 정기 호출하면 기본 24시간 점검 및 수정 후 6시간 집중 관찰 간격을 적용할 수 있습니다.
- 16개 MCP 도구가 상태조회·승인 대기·로그점검·유지보수·개선 제안·이미 승인된 패치 적용을 제공합니다.
- **MCP에는 승인 생성 도구가 없습니다.** 중요 변경이나 메뉴/기능 개선은 운영자가 별도 로컬 쉘에서 `approve --app 앱ID --id 제안ID --no-apply`를 실행한 다음 봇으로 적용할 수 있습니다.
- 기본 `mcp_allow_execution=true`, `mcp_allow_registration=false`, `mcp_allow_settings_changes=false`. `auto_fix=true` 상태에서 유지보수를 실행하면 일부 저위험 버그가 실제로 수정될 수 있으므로 주의하세요.
- 메시지 봇에 호스트 셸/파일 권한이 열려 있다면 MCP 승인 제한만으로는 충분하지 않습니다. 운영체제와 봇의 권한 제한을 함께 적용해야 합니다.

**상세 설정 및 보안, Hermes·OpenClaw cron 예제:** [`references/MCP.md`](MCP.md)
