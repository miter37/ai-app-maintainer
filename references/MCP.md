# MCP integration (Hermes Agent, OpenClaw, Codex, Claude Code)

`ai-app-maintainer` supports **local STDIO MCP** without additional Python packages. It is an **MCP tool server** alongside the existing `SKILL.md` and CLI, not a hosted API or a process that schedules itself.

**MCP transport:** JSON-RPC 2.0 over newline-delimited UTF-8 STDIO. Tested using local client/server protocol roundtrips; full integration with every external agent build is not yet certified. No TCP port, GUI, OAuth flow, or extra API key is created.

> **Trust boundary:** An always-on bot may be reachable through Telegram/Discord/other channels. Only install this MCP on a trusted host with access to the intended application folders. A bot with unrestricted local terminal or filesystem access can bypass MCP-specific tool restrictions by invoking the CLI or editing files; **MCP tool restrictions are not an OS security sandbox**. Restrict the agent's shell/file tools or run it with separately limited OS permissions if users other than the owner can send it commands.

## 1. Prepare the host

```bash
git clone https://github.com/miter37/ai-app-maintainer.git
cd ai-app-maintainer

# Check runtime and MCP configuration (does not start the server)
python3 scripts/mcp_server.py --check

# Register your actual application and a harmless test command
python3 scripts/maintainer.py add \
  --app orders-api \
  --path /absolute/path/to/orders-api \
  --log 'logs/**/*.log' \
  --test 'python -m pytest -q'

# Start conservatively for new apps
python3 scripts/maintainer.py set-app --app orders-api --key auto_fix --value off

# Configure local AI CLI used for diagnosis, independently from your MCP client
python3 scripts/maintainer.py doctor
```

The **registered app source/log folders**, the **MCP server**, and the **chosen Codex/Claude CLI** must be accessible to the account running the MCP server. Hermes or OpenClaw can use their own model for chat, but the maintenance engine currently invokes whichever installed Codex/Claude Code CLI is named in `config.json` (`engine`). **MCP does not convert the host's model into the code-patching engine.** Make sure the chosen CLI is installed, logged in, and available in the MCP subprocess's `PATH`.

For `python3`, use an absolute Python interpreter path if the bot's service environment has a limited `PATH`. Use `py -3` on Windows where supported; the process must be able to open `scripts/mcp_server.py` at an absolute path.

## 2. Hermes Agent (persistent bot/gateway)

Edit `~/.hermes/config.yaml` to add a local STDIO server:

```yaml
mcp_servers:
  ai-app-maintainer:
    command: "python3"
    args:
      - "/absolute/path/to/ai-app-maintainer/scripts/mcp_server.py"
    # The server has 16 tools; you may narrow the toolset for a bot.
    tools:
      include:
        - maintenance_help
        - list_apps
        - get_settings
        - get_app_status
        - get_pending_changes
        - get_change_details
        - get_post_fix_monitoring
        - get_latest_report
        - run_maintenance
        - suggest_improvements
```

Start a new session (`hermes chat`), or run `/reload-mcp` in a running session. Hermes exposes the selected tools with an `mcp_<server>_<tool>` prefix. For long-running analysis/fixes, configure the server-specific MCP call timeout according to your Hermes version and environment.

**Example Hermes cron job:**

```bash
hermes cron create "every 1h" \
  "Use ai-app-maintainer MCP to run due-only maintenance. Then read pending changes and post-fix monitoring. Report regressions and changes needing human approval, including app/proposal IDs; otherwise give a brief quiet summary." \
  --name "AI app maintenance"
```

This *agent-based* cron job uses a Hermes model turn. Your local Codex/Claude Code CLI also consumes provider usage if maintenance is due. An alternative is scheduling `scripts/run_due.sh` directly via the OS scheduler and asking Hermes to report the resulting status in its own cron job.

Official reference: [Hermes MCP](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp) and [Hermes cron](https://hermes-agent.nousresearch.com/docs/user-guide/features/cron).

## 3. OpenClaw (persistent gateway/bot)

Register the local STDIO MCP:

```bash
openclaw mcp add ai-app-maintainer \
  --command python3 \
  --arg /absolute/path/to/ai-app-maintainer/scripts/mcp_server.py

openclaw mcp doctor ai-app-maintainer --probe
```

The corresponding managed MCP configuration is equivalent to:

```json5
{
  mcp: {
    servers: {
      "ai-app-maintainer": {
        command: "python3",
        args: ["/absolute/path/to/ai-app-maintainer/scripts/mcp_server.py"],
        enabled: true,
        transport: "stdio"
      }
    }
  }
}
```

OpenClaw's tool policy also applies to MCP-exposed tools. For a publicly reachable bot, **consider exposing only the read-only query tools** until you've independently restricted who can request actions. Tool policy on the gateway is a separate layer from `config.json` in this skill.

**Example OpenClaw cron job:**

```bash
openclaw cron add \
  --name "AI app maintenance" \
  --every 1h \
  --session isolated \
  --message "Using ai-app-maintainer MCP, run due-only maintenance, then check pending changes and post-fix regressions. Report app IDs and proposal IDs for human decisions; never approve on my behalf." 
```

The OpenClaw Gateway must remain active for cron jobs. Delivery to a messaging platform must be configured within OpenClaw. Neither the MCP server nor the skill itself sends notifications.

Official references: [OpenClaw connect MCP servers](https://docs.openclaw.ai/tools/mcp), [OpenClaw MCP CLI](https://docs.openclaw.ai/cli/mcp), [OpenClaw cron](https://docs.openclaw.ai/cli/cron).

## 4. Tool catalog

| MCP tool | Role | Effects |
| --- | --- | --- |
| `maintenance_help` | Commands and approval workflow | Read-only |
| `list_apps` | App inventory, due status and health | Read-only |
| `get_settings` | Global/effective JSON settings | Read-only |
| `get_app_status` | Latest check and active watches | Read-only |
| `get_history` | Bounded per-app JSONL audit events | Read-only |
| `get_pending_changes` | List pending/approved proposals | Read-only |
| `get_change_details` | Evidence and scope for one proposal | Read-only |
| `get_post_fix_monitoring` | Multi-day watches / regression signals | Read-only |
| `get_latest_report` | Markdown maintenance/suggestions report | Read-only |
| `inspect_logs` | Recent bounded/redacted log preview | Reads logs; no AI or source edit |
| `run_maintenance` | Due/all/specific app maintenance | **May apply narrow bugfixes** if auto-fix ON |
| `suggest_improvements` | Analyze feature/menu/UX opportunities | Writes proposals only; **never implements** |
| `apply_approved_change` | Apply one **previously human-approved** change | May edit source; tests/rollback apply |
| `register_app` | Add application path, log patterns and tests | **Off by default**; writes registry |
| `set_app_setting` | Change app-level policy | **Off by default**; writes registry |
| `set_global_setting` | Change allowlisted global policy | **Off by default**; cannot change MCP permissions |

The server advertises these tool names directly. Some MCP clients add a server prefix.

## 5. Local JSON authorization switches

By default `config.json` contains:

```json
{
  "mcp_allow_execution": true,
  "mcp_allow_registration": false,
  "mcp_allow_settings_changes": false,
  "auto_fix": true,
  "upgrade_suggestions": true
}
```

These are regular persisted booleans. **No UI is required.** The MCP cannot turn on its own permission flags. Only a trusted operator can change them via the **local CLI** (or by editing JSON):

```bash
# Fully read-only MCP: no maintenance execution or proposal generation
python3 scripts/maintainer.py config --key mcp_allow_execution --value off

# Enable app registration from a trusted bot (opt-in; review paths and tests)
python3 scripts/maintainer.py config --key mcp_allow_registration --value on

# Enable per-app/global maintenance settings changes from a trusted bot (opt-in)
python3 scripts/maintainer.py config --key mcp_allow_settings_changes --value on

# Disable source auto-edits while leaving diagnosis and proposal creation on
python3 scripts/maintainer.py config --key auto_fix --value off
```

MCP tool calls **reuse** the existing CLI's process lock for mutations. Using two agents concurrently does not grant two independent writers; an overlapping attempt returns an error. If a process dies and leaves `.maintainer.lock`, inspect running processes before removing the stale lock manually.

## 6. Human approval: deliberately not an MCP tool

**The MCP server has no `approve` tool.** It cannot infer that a user typed “yes” in a chat that might be impersonated or prompt-injected. The host cannot vouch for the identity behind every tool call. The operator must execute this local CLI command for a **specific** proposal:

```bash
# Review the proposal first (or use get_change_details in the bot)
python3 scripts/maintainer.py pending --app orders-api

# Approve, but DO NOT implement yet
python3 scripts/maintainer.py approve \
  --app orders-api \
  --id 1234567890abcd \
  --no-apply
```

That ID is an **example only**; use the real 14-character ID reported by `get_pending_changes`. After approval, tell the bot to call:

```text
apply_approved_change({"app_id": "orders-api", "proposal_id": "<actual-ID>"})
```

Or let the next `run_maintenance` apply existing approved proposals. The underlying engine verifies that the stored proposal was already approved, stages the change, tests it, applies bounded files, and starts multi-day monitoring. It never deploys or restarts an actual service. An operator with physical/OS access may intentionally choose to approve-and-apply in one trusted CLI action by omitting `--no-apply`.

> **Note:** Approval is enforced at the MCP tool layer, not against a client that also has unrestricted local shell/file access. Put identity/authorization controls in front of your messaging bot and isolate its OS permissions.

## 7. Operational behavior

- **Scheduling:** MCP itself is not a scheduler. Use Hermes/OpenClaw cron or OS scheduled tasks at least as often as your desired observation interval. `run_maintenance` without an `app_id` uses `--due` by default (24-hour normal cadence; 6-hour watch cadence by default).
- **Outputs:** JSON structured tool results. Failures return `isError: true` plus a short diagnostic. The server keeps protocol stdout clean and writes any diagnostics to stderr.
- **Model/provider:** This project uses the selected local Codex/Claude CLI. Provider billing and authentication are governed by that CLI. Changing the Hermes/OpenClaw chat model does not change the maintenance engine selection.
- **Logs and privacy:** Recent log data may contain sensitive information; redaction is best-effort and selected evidence can be supplied to the external model used by Codex/Claude. Do not expose the MCP or the registered app folders to untrusted operators.
- **Host tool timeouts:** AI analysis and patching can take minutes; increase the Hermes/OpenClaw MCP tool request timeout as appropriate. A timeout does not prove that a code change didn't occur; inspect `status`, `history`, and the app's `fixes/` records before retrying.
- **Deployment boundary:** `source_applied` means changed files plus configured tests, not a deployment/restart. Fixes should be verified against an actual running service separately where needed.
- **Protocol scope:** This server implements a small, tools-only subset of the MCP STDIO protocol. It does not implement MCP resources, sampling, elicitation, HTTP transport, or cancellation of an in-progress long-running fix.

## 8. Local verification

```bash
python3 scripts/mcp_server.py --check
python3 -m unittest discover -s tests -v
```

Tests include actual STDIO JSON-RPC roundtrips, tool schema validation, safety gates, and prior-approval-only application. Integration testing on your particular Hermes/OpenClaw and Codex/Claude versions remains necessary before unattended operation.
