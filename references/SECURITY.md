# 안전성 설계와 한계

이 스킬은 AI가 앱 코드를 자동 수정할 수 있는 권한을 다루므로 신뢰된 로컬 개발 환경에서 사용한다. 다음은 현재 구현의 조건과 한계다.

1. **승인 게이트:** `auto_fix=true`여도 버그 수정만 제한적으로 자동 허용한다. 심각도 low/medium, 위험 low, 높은 분석 확신도, 타임스탬프 확인 로그 근거, 파일 단서, 구체적 수정안, 등록 테스트가 모두 필요하다. 기능 추가, 메뉴 개편, UX 개선은 예외 없이 승인 필요. 자동 수정 후보도 파일 경로·변경량 검증을 통과해야 한다.
2. **단계별 작업:** AI 분석은 주요 비밀·로그·의존성 폴더를 제외한 임시 복제본을 읽는다. 패치 역시 임시 작업본에서만 작성한다. 수정 파일 목록, 파일 크기, 변경 줄 수, 확장자 및 민감 경로 제한을 검사한다. 적용 전 파일 해시를 재확인하며, 수정 전 원본을 스킬 하위에 백업하고 검증 실패 시 수정 파일을 복원한다.
3. **로그 비식별화:** 토큰/Bearer/일부 비밀 키 패턴을 가리는 정규식 처리를 하지만 모든 개인정보·민감 정보 검출을 보장하지 않는다. 분석에 민감 정보가 들어가기 전에 앱 로그 설계를 점검한다. 모니터링 이력도 개인 환경에서 기밀로 다룬다.
4. **CLI 접근 제한:** Codex 분석은 `read-only`, 패치는 `workspace-write` 샌드박스 모드로 요청한다. Claude Code 분석/수정은 `--safe-mode --restricted`와 제한된 도구 집합으로 실행한다. CLI 버전/플랫폼의 지원 여부와 실제 샌드박스 경계를 확인해야 한다. **코드 실행과 파일 접근이 가능한 AI 도구는 완전한 보안 격리가 아니다.** 고보안 운영 환경은 OS 사용자, 컨테이너 또는 별도 격리를 사용한다.
5. **테스트는 사용자 책임:** 등록된 테스트 명령은 실행 시 로컬 프로세스로 실제 실행되며, 스테이징과 원본 양쪽에서 실행한다. 이를 변경 없는 테스트·검증 명령으로만 구성한다. 테스트 자체가 DB/외부 서버/실서비스에 부작용을 일으키면 이 스킬은 이를 롤백할 수 없다.
6. **적용의 의미:** `source_applied`는 파일 변경과 테스트 통과다. 배포, DB 마이그레이션, 시스템 서비스 재시작, 환경 변수 변경, 데이터 이관은 자동 수행하지 않는다. 실행 서비스의 배포 시점이 다르면 이후 로그 기반 관찰도 효과를 확인하지 못할 수 있다.
7. **후속 관찰 한계:** 기존 오류의 고유 문구를 찾아 재발을 탐지한다. 새 버그는 AI 재분석으로 발견될 수 있지만 로그가 부족하거나 새 오류 문구로 바뀌는 경우 탐지를 놓칠 수 있다. `stable_observed`는 정상 보증이 아니다.
8. **구독 이용:** AI 분석·패치에 로컬 `codex` 또는 `claude` 명령을 이용한다. 앱 스킬 자체가 외부 유료 API를 직접 호출하지 않는다. 그러나 사용한 CLI가 API 키로 인증되었거나 구독 사용 한도를 초과했다면 비용/실행 제한은 각 제공자의 현재 설정에 달려 있다.
9. **이력 관리:** 폴더에는 로그 발췌, 변경 전 소스 백업, 제안 및 분석 기록이 포함될 수 있다. 기본 `.gitignore`가 `managed-apps/*/`와 `reports/*`을 무시하더라도 직접 업로드하거나 강제 커밋하면 유출 위험이 있다.
10. **외부 승인 채널 없음:** 스킬 폴더 내 JSON/Markdown으로 승인 대기 항목을 남긴다. 이메일·메신저·푸시 알림이나 상시 실행 대시보드는 없다. 예약 실행은 OS 스케줄러를 별도로 등록해야 한다.

## MCP / always-on agent threat model

- The local STDIO MCP server is a thin tool facade over the same CLI and JSON policies. It does not open a network port.
- `run_maintenance` can edit source for eligible bug fixes when global/per-app `auto_fix=true`; enabling an MCP server is not synonymous with read-only access.
- There is intentionally no MCP approval tool. Only the trusted **local operator CLI** can mark a proposal approved; a separate `apply_approved_change` tool checks that recorded approval before attempting to implement.
- The MCP's registration and settings mutations are disabled by default. Config keys `mcp_allow_registration` and `mcp_allow_settings_changes` can be enabled only locally.
- These are **application-level gates, not authentication or OS sandboxing**. A chatbot with host shell access can invoke the CLI or edit the JSON records, bypassing MCP-only gates. Secure the agent host, its messaging-channel authentication, file permissions, and shell tools separately.
- No MCP elicitation, HTTP listener, cancellation protocol, session/user identity attestations, or built-in alert delivery is implemented.
- More details: `references/MCP.md`.
