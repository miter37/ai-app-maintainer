# ai-app-maintainer

### Your AI coding agent fixed the bug. Who makes sure it stays fixed?

**ai-app-maintainer** is a local, skill-based maintenance workflow for **OpenAI Codex** and **Claude Code**, now also exposing a **local MCP tool server for always-on agents such as Hermes Agent and OpenClaw**. Register the applications you want it to look after, point it at their logs, and let your existing AI coding CLI help investigate recurring problems, prepare bounded fixes, and suggest improvements.

The important part: **maintenance does not end when a patch passes its tests.** Every successfully applied source fix starts a configurable, multi-day observation period with more frequent checks for regressions.

**No web dashboard. No database server. No new agent platform.** Just a `SKILL.md`, an optional STDIO MCP server, Python standard-library scripts, JSON settings, and a separate maintenance history for every registered app.

> **Project status: early-stage.** The automated policy and file-handling paths and a local MCP wire-protocol roundtrip have tests, but live, unattended integration with every Hermes/OpenClaw, Codex/Claude Code version and application stack has **not** been validated. Start with auto-fix disabled, review the evidence, and enable it selectively.

## The idea in 30 seconds

Most coding agents work on a request, produce a fix, and stop. Applications don't stop changing after that.

`ai-app-maintainer` adds an ongoing, evidence-driven loop:

```text
Register application folder + log patterns + safe test commands
                         |
                Scheduled inspection
                 (24h by default)
                         |
              Recent logs + source code
              + previous maintenance history
                         |
                  AI investigates
                         |
            +------------+-------------+
            |                          |
   Narrow, low-risk bug         Important / uncertain
   with sufficient evidence     change, or new feature / UX idea
            |                          |
   Auto-fix enabled?            Proposal recorded
   Tests configured?            Human approval required
            |                          |
   Stage -> validate -> test     Approve a specific proposal
   -> back up -> apply          -> stage -> validate -> test
   -> test again                -> back up -> apply
            |                          |
            +------------+-------------+
                         |
               Post-fix watch starts
               (5 days by default,
                checks every 6 hours)
                         |
              Per-app history + reports
```

The two paths are deliberately different: **a small, well-supported bug fix may be automated; a feature, menu, or UX change never is.**

## What it does

| Capability | Behavior |
| --- | --- |
| **Log-driven maintenance** | Reads a configurable recent window (24 hours by default) from log patterns registered per application. Uses source code and prior maintenance records to investigate. |
| **Constrained automatic fixes** | Can apply narrowly scoped, low-risk bug fixes when evidence, confidence, test availability, and patch limits permit. Disable globally or per app. |
| **Human approval gate** | Holds high-impact, uncertain, security-sensitive, configuration, and other non-eligible changes for explicit approval. |
| **Improvement discovery** | Looks for justified feature, menu, and UX improvements when enabled (on by default). Suggestions are **never** implemented without approval. |
| **Post-fix watch** | For several days after a successful fix, checks for previous error markers and optionally reruns your safe smoke tests at a shorter interval. |
| **Persistent per-app memory** | Records inspections, findings, proposals, approvals, fixes, backups, regression watches, and a chronological audit trail under the skill folder. |
| **Multiple apps, one skill** | Each registered application has its own settings and history. Codex and Claude Code can share the same installed skill folder. |
| **Headless by design** | CLI and optional local STDIO MCP, plus an external scheduler. No GUI, web listener, hosted backend, or third-party Python packages. |
| **MCP for persistent agents** | Hermes/OpenClaw can query status and history, run due maintenance, generate upgrade suggestions, and report approvals through 16 typed tools. No MCP tool can grant an approval. |

This is **application source maintenance**, not an OS package updater. It does not run `apt upgrade`, update every installed program, or automatically deploy to production.

## Quick start

### 1. Prerequisites

- **Python 3.10+** and access to the application's source folder and logs.
- An installed, authenticated **Codex CLI** or **Claude Code CLI** (`codex` or `claude` on `PATH`).
- At least one **safe, repeatable test or smoke-check command** for any app where automatic patching should be permitted.
- A scheduler (cron, launchd, or Windows Task Scheduler) **only if** you want unattended recurring runs.

On Windows, use `py -3` wherever the examples show `python3`.

The skill invokes your locally configured CLI; it does not ask you to put a provider API key in this repository. **Authentication and billing follow that CLI's actual configuration**, which may be a subscription login or API-key billing. Check your environment before scheduling runs.

### 2. Get the skill and install it

```bash
git clone https://github.com/miter37/ai-app-maintainer.git
cd ai-app-maintainer

# Link the same folder into both agents' user-level skills directories.
python3 scripts/install.py --agent both --scope user

# Confirm Python, configured engine, and CLI availability.
python3 scripts/maintainer.py doctor
```

The installer links this single source directory into:

- **Codex:** `~/.agents/skills/ai-app-maintainer/`
- **Claude Code:** `~/.claude/skills/ai-app-maintainer/`

It will **not overwrite** an existing different skill at either location. Windows uses a directory junction if a symlink is unavailable. You can instead install for a single agent (`--agent codex` or `--agent claude`) or for a project (`--scope project --project-root /absolute/path/to/repo`).

> Keep the cloned skill folder in a permanent location. Its JSON settings and local app histories live inside it.

### 3. Register an application

From the **`ai-app-maintainer` directory**:

```bash
python3 scripts/maintainer.py add \
  --app orders-api \
  --path /absolute/path/to/orders-api \
  --log 'logs/**/*.log' \
  --log 'logs/**/*.jsonl' \
  --test 'python -m pytest -q'
```

`--app` is a stable ID for this app's separate records; `--path` is the **existing application directory**. Log globs are relative to that directory and can be repeated. The test command runs without a shell and **must not** modify production data, trigger deployment, or perform destructive operations. Replace the example test with one that is genuinely safe for your project.

To inspect what was registered:

```bash
python3 scripts/maintainer.py list
```

### 4. Inspect first, then run maintenance

```bash
# Read recent logs without involving an AI agent or editing code.
python3 scripts/maintainer.py inspect --app orders-api

# Run AI diagnosis, create approval requests, and apply only eligible fixes.
python3 scripts/maintainer.py run --app orders-api

# See what happened and what still requires a decision.
python3 scripts/maintainer.py report --app orders-api
python3 scripts/maintainer.py pending --app orders-api
python3 scripts/maintainer.py status --app orders-api
```

**Recommended first run:** turn off auto-fix until you've confirmed your log selection, test command, access permissions, and approval behavior:

```bash
python3 scripts/maintainer.py set-app --app orders-api --key auto_fix --value off
```

Turn it on for this app when you're comfortable with the boundaries:

```bash
python3 scripts/maintainer.py set-app --app orders-api --key auto_fix --value on
```

## Always-on agents: local MCP for Hermes Agent and OpenClaw

The **same maintenance engine** is accessible three ways: the skill's natural-language instructions, the CLI, or a **headless MCP STDIO server**. No new agent platform, hosted API, listening port, or external Python package is required.

**Check your MCP server:**

```bash
python3 scripts/mcp_server.py --check
```

**Hermes Agent:** add the following to `~/.hermes/config.yaml` (preserving other existing settings):

```yaml
mcp_servers:
  ai-app-maintainer:
    command: "python3"
    args: ["/absolute/path/to/ai-app-maintainer/scripts/mcp_server.py"]
```

Then start a new Hermes session or run `/reload-mcp`. Hermes exposes the tools with an MCP server prefix. For an hourly check using Hermes's own scheduler:

```bash
hermes cron create "every 1h" \
  "Use ai-app-maintainer MCP to run due-only maintenance and report regressions or pending human approvals with app/proposal IDs." \
  --name "AI app maintenance"
```

**OpenClaw:** register and probe the STDIO server:

```bash
openclaw mcp add ai-app-maintainer \
  --command python3 \
  --arg /absolute/path/to/ai-app-maintainer/scripts/mcp_server.py

openclaw mcp doctor ai-app-maintainer --probe
```

Then configure an hourly agent check (OpenClaw Gateway must be running):

```bash
openclaw cron add \
  --name "AI app maintenance" \
  --every 1h \
  --session isolated \
  --message "Use ai-app-maintainer MCP to run due-only maintenance, then report pending changes and regressions. Never approve a change on my behalf."
```

Those jobs use the agent's scheduler and messaging delivery. The **MCP server does not schedule jobs or send messages on its own.** Running due maintenance still launches the configured *local* Codex/Claude Code CLI when an analysis is needed; Hermes/OpenClaw's own chat model is not substituted for that code-editing engine.

### Built-in approval boundary and MCP permissions

MCP tools cover app discovery, recent log previews, maintenance history, pending proposals, multi-day fix watches, maintenance execution, feature suggestions, and explicitly preapproved patch application.

**MCP does not expose `approve_change`.** A bot cannot approve a feature or uncertain fix through an MCP tool. An actual operator must first review its proposal and authorize the exact ID from a trusted local shell:

```bash
python3 scripts/maintainer.py pending --app orders-api
python3 scripts/maintainer.py approve --app orders-api --id REAL_14_HEX_ID --no-apply
```

Afterwards the bot can use `apply_approved_change`, or the next due run can apply the approved change. Do not substitute the placeholder ID above for an actual proposal ID.

All MCP permissions are ordinary booleans inside `config.json`:

| Setting | Default | Effect |
| --- | --- | --- |
| `mcp_allow_execution` | `true` | Expose maintenance execution and feature suggestion tools; **source auto-fix may occur** if `auto_fix=true`. |
| `mcp_allow_registration` | `false` | Allow a bot to register new app roots and test commands only after local opt-in. |
| `mcp_allow_settings_changes` | `false` | Allow changes to a limited set of app/global settings only after local opt-in. MCP cannot enable its own gates. |

For an inspection-only rollout:

```bash
python3 scripts/maintainer.py config --key mcp_allow_execution --value off
python3 scripts/maintainer.py config --key auto_fix --value off
```

**Security note for messaging bots:** MCP approval gating is a **tool interface policy**, not protection from an unrestricted shell/file tool. Restrict host access and messaging permissions separately. Only run the MCP server on a machine that should be allowed to see the registered source and logs.

For all 16 tool names, Hermes/OpenClaw configuration options, unattended-operation caveats and approval examples, read **[MCP integration guide](references/MCP.md)**. Refer to the official [Hermes MCP](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp) and [OpenClaw MCP](https://docs.openclaw.ai/tools/mcp) docs for client-specific configuration.

## What happens after a fix?

This is the feature that motivated the project.

Suppose the agent patches a recurring request-handling bug. A passing test at 2:00 p.m. is useful, but it doesn't tell you what will happen tomorrow.

When a source fix is successfully applied, the skill creates a **watch record** for that fix. With default settings:

- The watch remains active for **5 days**.
- The app becomes eligible for an inspection every **6 hours** instead of its normal 24-hour interval.
- New timestamped log entries are checked for distinctive markers associated with the original error; the same entries are not counted repeatedly as new evidence.
- Registered safe smoke tests can run again during the observation window.
- Repeated errors or failed tests move the watch toward **regression suspected** / **needs review**; insufficient evidence remains explicitly inconclusive.

```bash
# Change observation duration and cadence.
python3 scripts/maintainer.py config --key monitor_days --value 7
python3 scripts/maintainer.py config --key monitor_check_every_hours --value 4

# Read individual observation states and the audit trail.
python3 scripts/maintainer.py status --app orders-api
python3 scripts/maintainer.py history --app orders-api
```

A quiet log is **not** proof of a healthy service. The watch distinguishes a lack of observed recurrence from verified behavior, and it only runs on schedule after you configure an external scheduler. **Applying a source patch is not the same as deploying or restarting your running service.**

## Feature and UX proposals: approval is mandatory

Maintenance shouldn't have to mean "only fix what is broken." With improvement discovery enabled, the agent may identify a more efficient workflow, a missing capability, or a confusing menu structure.

```bash
# Generate improvement proposals. No source code is changed.
python3 scripts/maintainer.py suggest --app orders-api

# Review pending proposals and their IDs.
python3 scripts/maintainer.py pending --app orders-api

# Implement only a specifically approved proposal.
python3 scripts/maintainer.py approve --app orders-api --id a1b2c3d4e5f678

# Or reject it; the decision is retained.
python3 scripts/maintainer.py reject --app orders-api --id a1b2c3d4e5f678
```

The ID above is illustrative. Replace it with the proposal ID copied **exactly** from `pending` (a 14-character lowercase hexadecimal ID). Approval authorizes that proposal's scoped implementation, subject to staging and verification safeguards. You can also approve now and defer application with `--no-apply`.

**Turning on suggestions does not turn on automatic feature development.** These are separate settings and separate approval rules.

## Configuration: two switches, no settings screen

All persistent options are plain JSON in [`config.json`](config.json), with optional per-app overrides in [`registry.json`](registry.json).

```json
{
  "engine": "codex",
  "lookback_hours": 24,
  "run_every_hours": 24,
  "auto_fix": true,
  "upgrade_suggestions": true,
  "monitor_days": 5,
  "monitor_check_every_hours": 6,
  "monitor_run_tests": true
}
```

This is an **excerpt**, not the entire configuration file.

| Option | Default | Meaning |
| --- | --- | --- |
| `engine` | `codex` | Select `codex` or `claude` for analysis and patch generation. |
| `lookback_hours` | `24` | Log evidence window, in hours. |
| `run_every_hours` | `24` | Normal per-app inspection interval. |
| `auto_fix` | `true` | Permit narrowly eligible automatic bug fixes. Set `false` to require review instead. |
| `upgrade_suggestions` | `true` | Allow feature/UX improvement discovery. Never removes the approval gate. |
| `monitor_days` | `5` | Days to watch an applied fix more closely. |
| `monitor_check_every_hours` | `6` | Inspection interval during an active fix watch. |
| `monitor_run_tests` | `true` | Rerun registered safe tests during post-fix watches. |

Change a global setting with the CLI:

```bash
python3 scripts/maintainer.py config --key engine --value claude
python3 scripts/maintainer.py config --key auto_fix --value off
python3 scripts/maintainer.py config --key upgrade_suggestions --value on
python3 scripts/maintainer.py config --key lookback_hours --value 48
```

Override a setting for one app:

```bash
python3 scripts/maintainer.py set-app --app orders-api --key auto_fix --value off
python3 scripts/maintainer.py set-app --app orders-api --key upgrade_suggestions --value off
```

Per-app overrides take precedence over global values. See the complete [settings and file schema](references/SCHEMA.md).

## Run it on a schedule

There is **no always-on process inside the skill or MCP server**. Your operating system or Hermes/OpenClaw starts maintenance when scheduled; the engine decides which apps are due. An hourly scheduler is sufficient for the default 24-hour and 6-hour cadences.

**Linux / macOS (cron):**

```cron
0 * * * * /absolute/path/to/ai-app-maintainer/scripts/run_due.sh
```

**Windows (Task Scheduler):** create a task that runs hourly, starts `powershell.exe`, and passes:

```powershell
-NoProfile -File "C:\path\to\ai-app-maintainer\scripts\run_due.ps1"
```

**Manual due-only run:**

```bash
python3 scripts/maintainer.py run --due
```

Scheduled processes must be able to find Python and the selected AI CLI, including its authenticated session. Computers that are asleep or offline won't run your schedule unless your OS is configured to wake them. Execution output is appended to `reports/scheduler.log`.

## Ask the skill directly

Once installed, use natural-language requests inside your coding agent. Questions about *how* to do something are documentation requests; they **do not** trigger a repair or an app registration.

**Codex** (explicit skill invocation):

```text
$ai-app-maintainer help
$ai-app-maintainer How do I register another app?
$ai-app-maintainer Inspect orders-api and summarize any regressions.
```

**Claude Code** (explicit skill invocation):

```text
/ai-app-maintainer help
/ai-app-maintainer How do upgrade suggestions work?
/ai-app-maintainer Check whether our last fix is holding up.
```

You can also ask an agent to use `ai-app-maintainer` in natural language. Explicit invocation is the most predictable way to select the skill.

For CLI help independent of an agent:

```bash
python3 scripts/maintainer.py help
python3 scripts/maintainer.py help register
python3 scripts/maintainer.py help upgrade
python3 scripts/maintainer.py help monitor
```

## Where the history goes

The skill keeps **one directory per registered app** and does not relocate that app's original source code.

```text
ai-app-maintainer/
├── SKILL.md                    # Agent instructions and approval policy
├── config.json                 # Global switches and intervals
├── registry.json               # Registered app paths + overrides
├── scripts/                    # CLI, MCP stdio server, agent bridge, schedulers
├── references/                 # Policies and usage guides
├── managed-apps/
│   └── orders-api/
│       ├── inspections/        # Evidence and analysis for each run
│       ├── findings/           # Diagnosed findings
│       ├── proposals/          # Pending, approved, rejected, applied
│       ├── fixes/              # Patch and verification records
│       ├── monitors/           # Multi-day post-fix observations
│       ├── backups/            # Pre-change source backups
│       ├── history.jsonl       # Machine-readable audit log
│       ├── history.md          # Human-readable timeline
│       ├── latest-report.md
│       └── latest-suggestions.md
└── reports/                    # Consolidated reports and scheduler log
```

The `.gitignore` excludes generated app histories and reports because they can contain log excerpts, internal code, paths, and backups. **Do not force-add them to a public repository.**

## How auto-fix is constrained

Auto-fix is not an unconstrained "let an agent rewrite my app" mode. Among other conditions, the current implementation requires:

1. A **bugfix**, not a feature request, refactor, dependency migration, or speculative improvement.
2. A **low-risk** assessment with sufficient confidence, specific file hints, and timestamp-verifiable log evidence.
3. **Registered tests** for automatic application (the default policy).
4. A patch generated in a **filtered temporary working copy** rather than directly in the original application.
5. File/path restrictions, changed-file and patch-size bounds, a **staging test**, original-file hash checks, **backups**, and a **post-application test**.

If those checks do not pass, the change is not silently installed. Important and uncertain changes require an explicit approval decision. A failed post-application verification attempts to restore the affected source files from backup.

**Security limitations matter:** tests are real local processes and may have external side effects; log redaction is best-effort; agent sandboxes are not perfect isolation; provider CLIs may transmit selected source/log context to their services. Do not point unattended repair at sensitive production systems without a deliberate security review and a tested recovery plan. Read [security boundaries and limitations](references/SECURITY.md).

## What this project does *not* do

- **No auto-deploy, restart, database migration, or production traffic cutover.** `source_applied` means source files were changed and the configured verification passed (or a specific unverified approval waiver was given).
- **No built-in push notifications or hosted approval inbox.** Pending decisions are stored locally; Hermes/OpenClaw can report them using their own scheduled messaging jobs.
- **No guarantee that every regression appears in logs.** Missing timestamps, truncated logs, quiet services, and incomplete tests limit what can be known.
- **No guarantee of free AI usage.** Subscription entitlements, API-key configuration, rate limits, and billing belong to your chosen CLI/provider.
- **No full end-to-end compatibility certification yet.** The CLI integration needs to be exercised with your installed Codex/Claude Code version and application environment.

## Development and testing

The orchestration code uses the **Python standard library only**. Run the test suite from the repository root:

```bash
python3 -m unittest discover -s tests -v
```

The current test suite covers 41 cases, including MCP STDIO roundtrips, tool argument validation, restrictive MCP defaults, approval boundaries, feature-only suggestions, bounded auto-fix behavior, rollback, timestamp-aware log collection, shared skill installation, and regression monitoring. **These are local/unit-level checks, not a production reliability claim.**

Useful references:

- [Agent workflow instructions](SKILL.md)
- [Full configuration and storage schema](references/SCHEMA.md)
- [Security model and operational caveats](references/SECURITY.md)
- [Korean usage guide](references/USAGE_KO.md)
- [MCP setup for Hermes Agent / OpenClaw](references/MCP.md)
- [Codex skills documentation](https://developers.openai.com/api/docs/guides/tools-skills)
- [Claude Code CLI reference](https://code.claude.com/docs/en/cli-reference)

## Contributing and feedback

This project is intended for developers managing several evolving apps who want **a repeatable maintenance process with clear limits and an audit trail**—not another dashboard to babysit.

Bug reports, platform compatibility findings, security reviews, and improvements to the maintenance policy are welcome through GitHub Issues. If you propose new automation, please include the failure mode it addresses, the approval boundary, and a way to test it. Changes that weaken the mandatory approval rule for features/UX are out of scope.

### License

Licensed under the **MIT License**. See [LICENSE](LICENSE) for the full terms.

Copyright (c) 2026 miter37.

---

**The goal isn't to make an AI agent say “fixed” more often. It's to make it accountable for what happened after the fix.**
