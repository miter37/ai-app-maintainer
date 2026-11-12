"""MCP stdio wire and approval-boundary tests; requires no MCP SDK or AI CLI."""
from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import core
import mcp_server
import mcp_tools
import workflow


class WireProtocolTests(unittest.TestCase):
    def test_initialize_protocol_and_instructions(self):
        reply = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "clientInfo": {"name": "Hermes", "version": "1"}}})
        self.assertEqual(reply["result"]["protocolVersion"], "2025-06-18")
        self.assertTrue(reply["result"]["capabilities"]["tools"] == {"listChanged": False})
        self.assertIn("human operator", reply["result"]["instructions"].lower())

    def test_unknown_protocol_negotiates_stable_version(self):
        reply = mcp_server.handle({"jsonrpc": "2.0", "id": "x", "method": "initialize", "params": {
            "protocolVersion": "2099-01-01"}})
        self.assertEqual(reply["result"]["protocolVersion"], mcp_server.DEFAULT_PROTOCOL)

    def test_tools_schema_and_no_approve_tool(self):
        reply = mcp_server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = {tool["name"] for tool in reply["result"]["tools"]}
        self.assertIn("run_maintenance", names)
        self.assertIn("get_post_fix_monitoring", names)
        self.assertIn("apply_approved_change", names)
        self.assertNotIn("approve_change", names)
        self.assertNotIn("approve", names)
        for tool in reply["result"]["tools"]:
            self.assertFalse(tool["inputSchema"]["additionalProperties"])

    def test_notifications_get_no_reply(self):
        self.assertIsNone(mcp_server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_unknown_method_and_missing_params(self):
        reply = mcp_server.handle({"jsonrpc": "2.0", "method": "not-a-real-method", "id": 5})
        self.assertEqual(reply["error"]["code"], -32601)
        reply = mcp_server.handle({"jsonrpc": "2.0", "method": "tools/call", "id": 6,
                                   "params": {"arguments": {}}})
        self.assertEqual(reply["error"]["code"], -32602)

    def test_ping(self):
        self.assertEqual(mcp_server.handle({"jsonrpc": "2.0", "method": "ping", "id": 3})["result"], {})

    def test_oversize_messages_and_invalid_json(self):
        protocol = b'{"jsonrpc":"2.0","method":"ping","id":33}\n'
        stream = io.BytesIO(b"bad-json\n" + b"[" + b"0" * (mcp_server.MAX_MESSAGE_BYTES + 10) + b"]\n" + protocol)
        result = io.BytesIO()
        mcp_server.serve(stream, result)
        decoded = [json.loads(x) for x in result.getvalue().splitlines()]
        self.assertEqual([x.get("error", {}).get("code") for x in decoded[:2]], [-32700, -32700])
        self.assertEqual(decoded[2]["id"], 33)

    def test_real_stdio_maintenance_observe_only(self):
        """End-to-end: MCP tool -> CLI lock -> log inspection -> status file."""
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            skill, app = base / "skill", base / "app"
            (skill / "scripts").mkdir(parents=True)
            (app / "logs").mkdir(parents=True)
            (app / "source.py").write_text("VALUE = 1\n", encoding="utf-8")
            (app / "logs" / "events.log").write_text(core.stamp() + " INFO healthy\n", encoding="utf-8")
            for filename in ("core.py", "workflow.py", "agent_bridge.py", "mcp_tools.py", "mcp_server.py", "maintainer.py"):
                shutil.copy2(ROOT / "scripts" / filename, skill / "scripts" / filename)
            (skill / "config.json").write_text(json.dumps(core.DEFAULTS))
            (skill / "registry.json").write_text(json.dumps({"apps": {"test-app": {
                **core.APP_DEFAULTS, "path": str(app), "log_globs": ["logs/*.log"]}}}))
            msgs = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "run_maintenance", "arguments": {
                    "app_id": "test-app", "observe_only": True}}},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_app_status", "arguments": {
                    "app_id": "test-app"}}},
            ]
            cp = subprocess.run([sys.executable, str(skill / "scripts/mcp_server.py")],
                                input="\n".join(map(json.dumps, msgs)) + "\n", text=True,
                                capture_output=True, timeout=30)
            self.assertEqual(cp.returncode, 0, cp.stderr)
            replies = [json.loads(line) for line in cp.stdout.splitlines()]
            self.assertEqual(len(replies), 3)
            self.assertFalse(replies[1]["result"]["isError"])
            self.assertTrue(replies[1]["result"]["structuredContent"]["result"][0]["run_id"])
            self.assertTrue(replies[2]["result"]["structuredContent"]["state"]["last_run_at"])
            self.assertEqual((app / "source.py").read_text(), "VALUE = 1\n")
            self.assertTrue((skill / "managed-apps/test-app/history.jsonl").exists())

    def test_actual_subprocess_stdio_roundtrip(self):
        """Real subprocess, real protocol parsing, isolated registry/config."""
        with tempfile.TemporaryDirectory() as temp:
            skill = Path(temp) / "skill"
            (skill / "scripts").mkdir(parents=True)
            for filename in ("core.py", "workflow.py", "agent_bridge.py", "mcp_tools.py", "mcp_server.py", "maintainer.py"):
                shutil.copy2(ROOT / "scripts" / filename, skill / "scripts" / filename)
            (skill / "config.json").write_text(json.dumps(core.DEFAULTS), encoding="utf-8")
            (skill / "registry.json").write_text('{"apps":{}}', encoding="utf-8")
            msgs = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "list_apps", "arguments": {}}},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "register_app", "arguments": {"app_id": "foo", "path": "/tmp"}}},
                {"jsonrpc": "2.0", "id": 5, "method": "ping"},
            ]
            cp = subprocess.run([sys.executable, str(skill / "scripts" / "mcp_server.py")],
                                input="\n".join(map(json.dumps, msgs)) + "\n", capture_output=True,
                                text=True, timeout=20)
            self.assertEqual(cp.returncode, 0, cp.stderr)
            result = [json.loads(line) for line in cp.stdout.splitlines()]
            self.assertEqual([m["id"] for m in result], [1, 2, 3, 4, 5])
            self.assertEqual(result[0]["result"]["protocolVersion"], "2025-11-25")
            self.assertEqual(result[2]["result"]["structuredContent"]["apps"], [])
            self.assertTrue(result[3]["result"]["isError"])
            self.assertIn("mcp_allow_registration=false", result[3]["result"]["content"][0]["text"])
            self.assertEqual(result[4]["result"], {})
            self.assertEqual(json.loads((skill / "registry.json").read_text()), {"apps": {}})


class MCPPolicyFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.skill = root / "skill"
        self.app = root / "app"
        self.app.mkdir()
        (self.app / "logs").mkdir()
        (self.app / "service.py").write_text("VALUE = 0\n", encoding="utf-8")
        (self.app / "logs" / "app.log").write_text(core.stamp() + " INFO healthcheck ok\n")
        for mod, attr, value in [
            (core, "ROOT", self.skill), (core, "CONFIG", self.skill / "config.json"),
            (core, "REGISTRY", self.skill / "registry.json"),
            (core, "MANAGED", self.skill / "managed-apps"),
            (core, "REPORTS", self.skill / "reports"),
            (workflow, "REPORTS", self.skill / "reports"),
            (mcp_tools, "ROOT", self.skill),
        ]:
            p = patch.object(mod, attr, value)
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.temp.cleanup)
        core.ensure_initialized()
        reg = core.registry()
        reg["apps"]["test-app"] = {**core.APP_DEFAULTS, "path": str(self.app),
                                 "test_commands": [[sys.executable, "-c", "print(1)"]]}
        core.atomic_json(core.REGISTRY, reg)
        core.init_app_dirs("test-app")

    def test_read_only_tools_do_not_invoke_external_ai(self):
        with patch.object(mcp_tools, "_cli") as mocked:
            ids = mcp_tools.call("list_apps", {})
            self.assertEqual(ids["apps"][0]["id"], "test-app")
            self.assertTrue(mcp_tools.call("get_settings", {})["ok"])
            self.assertTrue(mcp_tools.call("get_app_status", {"app_id": "test-app"})["ok"])
            self.assertEqual(mcp_tools.call("get_history", {"app_id": "test-app"})["events"], [])
            self.assertEqual(mcp_tools.call("get_pending_changes", {})["pending"], [])
            self.assertEqual(mcp_tools.call("get_post_fix_monitoring", {"app_id": "test-app"})["monitors"], [])
            logs = mcp_tools.call("inspect_logs", {"app_id": "test-app"})
            self.assertEqual(logs["evidence"]["verified_lines"], 1)
            mocked.assert_not_called()

    def test_unknown_app_and_traversal_cannot_read(self):
        self.assertFalse(mcp_tools.call("get_app_status", {"app_id": "other-app"})["ok"])
        self.assertFalse(mcp_tools.call("get_history", {"app_id": "../outside"})["ok"])
        self.assertFalse(mcp_tools.call("get_change_details", {"app_id": "test-app", "proposal_id": "../../foo"})["ok"])
        self.assertFalse(mcp_tools.call("inspect_logs", {"app_id": "test-app", "preview_lines": 100000})["ok"])
        self.assertFalse(mcp_tools.call("list_apps", {"extra": "malicious"})["ok"])
        self.assertFalse(mcp_tools.call("run_maintenance", {"due_only": "false"})["ok"])

    def test_default_registration_and_settings_disabled(self):
        with patch.object(mcp_tools, "_cli") as mocked:
            r = mcp_tools.call("register_app", {"app_id": "example", "path": str(self.app)})
            self.assertFalse(r["ok"])
            self.assertIn("mcp_allow_registration=false", r["error"])
            self.assertFalse(mcp_tools.call("set_app_setting", {"app_id": "test-app", "key": "auto_fix", "value": "on"})["ok"])
            self.assertFalse(mcp_tools.call("set_global_setting", {"key": "auto_fix", "value": "off"})["ok"])
            mocked.assert_not_called()

    def test_all_gate_flags_must_be_real_booleans(self):
        cfg = core.config()
        cfg["mcp_allow_registration"] = "true"
        core.atomic_json(core.CONFIG, cfg)
        self.assertFalse(mcp_tools.call("register_app", {"app_id": "example", "path": str(self.app)})["ok"])

    def test_registration_enabled_only_from_local_config(self):
        cfg = core.config()
        cfg["mcp_allow_registration"] = True
        core.atomic_json(core.CONFIG, cfg)
        with patch.object(mcp_tools, "_cli", return_value={"registered": "another"}) as mocked:
            self.assertTrue(mcp_tools.call("register_app", {"app_id": "another", "path": str(self.app),
                                                       "log_patterns": ["logs/*.log"],
                                                       "test_commands": ["python -m unittest"]})["ok"])
            cmd = mocked.call_args.args[0]
            self.assertEqual(cmd[:5], ["add", "--app", "another", "--path", str(self.app)])
            self.assertIn("--test", cmd)

    def test_execution_off_blocks_run_and_suggestions(self):
        cfg = core.config()
        cfg["mcp_allow_execution"] = False
        core.atomic_json(core.CONFIG, cfg)
        with patch.object(mcp_tools, "_cli") as mocked:
            self.assertFalse(mcp_tools.call("run_maintenance", {})["ok"])
            self.assertFalse(mcp_tools.call("suggest_improvements", {"app_id": "test-app"})["ok"])
            mocked.assert_not_called()

    def test_due_and_targeted_modes(self):
        with patch.object(mcp_tools, "_cli", return_value=[]) as mocked:
            mcp_tools.call("run_maintenance", {})
            self.assertEqual(mocked.call_args.args[0], ["run", "--due"])
            mcp_tools.call("run_maintenance", {"app_id": "test-app", "observe_only": True})
            self.assertEqual(mocked.call_args.args[0], ["run", "--app", "test-app", "--no-agent"])
            mcp_tools.call("run_maintenance", {"due_only": False})
            self.assertEqual(mocked.call_args.args[0], ["run", "--all"])

    def test_apply_denied_without_approval(self):
        with patch.object(mcp_tools, "_cli") as mocked:
            result = mcp_tools.call("apply_approved_change", {"app_id": "test-app", "proposal_id": "a" * 14})
            self.assertFalse(result["ok"])
            mocked.assert_not_called()

    def test_cli_preapproved_only_and_record_state(self):
        issue = {"id": "a" * 14, "status": "pending_approval", "title": "Improve menu", "kind": "ux"}
        proposal = core.app_dir("test-app") / "proposals" / (issue["id"] + ".json")
        core.atomic_json(proposal, issue)
        with patch.object(workflow, "implement") as implement:
            with self.assertRaises(ValueError):
                workflow.apply_preapproved("test-app", issue["id"])
            implement.assert_not_called()
        workflow.decide("test-app", issue["id"], True, apply=False)
        with patch.object(workflow, "implement", return_value={"id": "fix123"}) as implement:
            result = workflow.apply_preapproved("test-app", issue["id"])
            self.assertTrue(implement.call_args.kwargs["approved"])
        self.assertEqual(result["status"], "applied")
        self.assertEqual(core.load_json(proposal)["fix_id"], "fix123")

    def test_mcp_applies_only_preapproved(self):
        issue = {"id": "b" * 14, "status": "pending_approval", "title": "Improve menu", "kind": "ux"}
        proposal = core.app_dir("test-app") / "proposals" / (issue["id"] + ".json")
        core.atomic_json(proposal, issue)
        workflow.decide("test-app", issue["id"], True, apply=False)
        with patch.object(mcp_tools, "_cli", return_value={"status": "applied"}) as mocked:
            result = mcp_tools.call("apply_approved_change", {"app_id": "test-app", "proposal_id": issue["id"]})
            self.assertTrue(result["ok"])
            self.assertEqual(mocked.call_args.args[0], ["apply-approved", "--app", "test-app", "--id", issue["id"]])

    def test_mcp_cannot_toggle_own_permissions(self):
        cfg = core.config()
        cfg["mcp_allow_settings_changes"] = True
        core.atomic_json(core.CONFIG, cfg)
        with patch.object(mcp_tools, "_cli") as mocked:
            self.assertFalse(mcp_tools.call("set_global_setting", {"key": "mcp_allow_registration", "value": "on"})["ok"])
            mocked.assert_not_called()


if __name__ == "__main__":
    unittest.main()
