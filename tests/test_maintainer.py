"""Run with: python -m unittest discover -s tests -v  (no CLI subscription needed)."""
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import core
import workflow
import maintainer


def issue(kind="bugfix", risk="low", title="Repair widget error", severity="medium"):
    return {"title": title, "kind": kind, "severity": severity, "risk": risk,
            "confidence": 0.97, "why": "Repeatable logged failure",
            "evidence": ["RuntimeError: Widget not ready"],
            "file_hints": ["service.py"], "fix_instructions": "Set VALUE to 1 only.",
            "watch_markers": ["RuntimeError: Widget not ready"]}


class AppFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.skill = base / "skill"
        self.app = base / "app"
        self.app.mkdir()
        (self.app / "logs").mkdir()
        (self.app / "service.py").write_text("VALUE = 0\n", encoding="utf-8")
        self.log = self.app / "logs" / "app.log"
        self.log.write_text(core.stamp() + " ERROR RuntimeError: Widget not ready\n", encoding="utf-8")
        self.patchers = [
            patch.object(core, "ROOT", self.skill),
            patch.object(core, "CONFIG", self.skill / "config.json"),
            patch.object(core, "REGISTRY", self.skill / "registry.json"),
            patch.object(core, "MANAGED", self.skill / "managed-apps"),
            patch.object(core, "REPORTS", self.skill / "reports"),
            patch.object(workflow, "REPORTS", self.skill / "reports"),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.temp.cleanup)
        core.ensure_initialized()
        reg = core.registry()
        reg["apps"]["test-app"] = {**core.APP_DEFAULTS, "path": str(self.app),
            "test_commands": [[sys.executable, "-c", "import service; assert service.VALUE == 1"]]}
        core.atomic_json(core.REGISTRY, reg)
        core.init_app_dirs("test-app")

    def patch_code(self, engine, stage, *_):
        (stage / "service.py").write_text("VALUE = 1\n", encoding="utf-8")
        return "Changed service.py"

    def analysis(self, finding=None):
        return {"summary": "One issue", "overall_health": "needs_attention",
                "findings": [finding or issue()], "monitor_notes": []}

    def set_global(self, **changes):
        cfg = core.config()
        cfg.update(changes)
        core.atomic_json(core.CONFIG, cfg)

    def test_recent_log_collection_and_redaction(self):
        self.log.write_text(
            (core.stamp(core.now() - timedelta(days=3)) + " ERROR old error\n") +
            (core.stamp() + " ERROR RuntimeError: Widget not ready authorization:abcd123456\n"),
            encoding="utf-8")
        evidence = core.collect_logs(self.app, ["logs/**/*.log"], 24, core.config())
        self.assertEqual(evidence["verified_lines"], 1)
        self.assertNotIn("old error", json.dumps(evidence))
        self.assertNotIn("abcd123456", json.dumps(evidence))
        self.assertIn("[REDACTED]", json.dumps(evidence))

    def test_auto_patch_and_monitor_started(self):
        with patch.object(workflow, "run_analysis", return_value=self.analysis()), \
             patch.object(workflow, "run_patch", side_effect=self.patch_code):
            result = workflow.run_one("test-app")
        self.assertEqual(result["applied"], 1)
        self.assertEqual((self.app / "service.py").read_text(), "VALUE = 1\n")
        mon = workflow.read_monitors("test-app")[0]
        self.assertEqual(mon["status"], "watching")
        self.assertEqual(mon["observation_count"], 0)
        self.assertTrue(list((self.skill / "managed-apps/test-app/backups").glob("*/service.py")))

    def test_monitor_detects_marker_recurrence(self):
        with patch.object(workflow, "run_analysis", return_value=self.analysis()), \
             patch.object(workflow, "run_patch", side_effect=self.patch_code):
            workflow.run_one("test-app")
        # Post-fix log line; source regression warning is based on explicit timestamps.
        with self.log.open("a", encoding="utf-8") as f:
            f.write(core.stamp(core.now() + timedelta(seconds=1)) + " ERROR RuntimeError: Widget not ready\n")
        with patch.object(workflow, "run_analysis", return_value={
            "summary": "Monitoring only", "overall_health": "unknown", "findings": [], "monitor_notes": []}):
            workflow.run_one("test-app")
        mon = workflow.read_monitors("test-app")[0]
        self.assertEqual(mon["status"], "regression_suspected")
        self.assertEqual(mon["observation_count"], 1)

    def test_auto_fix_off_stops_automatic_patch(self):
        self.set_global(auto_fix=False)
        with patch.object(workflow, "run_analysis", return_value=self.analysis()), \
             patch.object(workflow, "run_patch") as edit:
            result = workflow.run_one("test-app")
            edit.assert_not_called()
        self.assertEqual(result["applied"], 0)
        proposal = list((self.skill / "managed-apps/test-app/proposals").glob("*.json"))[0]
        self.assertEqual(core.load_json(proposal)["status"], "pending_approval")

    def test_feature_always_waits_then_applies_after_approval(self):
        with patch.object(workflow, "run_analysis", return_value=self.analysis(issue("feature", "low", "Add caching menu"))), \
             patch.object(workflow, "run_patch") as edit:
            result = workflow.run_one("test-app")
            edit.assert_not_called()
        self.assertEqual(result["applied"], 0)
        proposal = core.load_json(next((self.skill / "managed-apps/test-app/proposals").glob("*.json")))
        self.assertEqual(proposal["status"], "pending_approval")
        with patch.object(workflow, "run_patch", side_effect=self.patch_code):
            approved = workflow.decide("test-app", proposal["id"], True)
        self.assertEqual(approved["proposal"]["status"], "applied")
        self.assertEqual((self.app / "service.py").read_text(), "VALUE = 1\n")

    def test_post_fix_test_failure_is_reported_in_watch(self):
        with patch.object(workflow, "run_analysis", return_value=self.analysis()), \
             patch.object(workflow, "run_patch", side_effect=self.patch_code):
            workflow.run_one("test-app")
        healthy = {"summary": "Watching", "overall_health": "unknown", "findings": [], "monitor_notes": []}
        with patch.object(workflow, "run_analysis", return_value=healthy), \
             patch.object(workflow, "run_tests", side_effect=RuntimeError("Follow-up smoke failed")):
            result = workflow.run_one("test-app")
        self.assertTrue(result["errors"])
        m = workflow.read_monitors("test-app")[0]
        self.assertEqual(m["status"], "regression_suspected")
        self.assertEqual(m["test_fail_count"], 1)

    def test_auto_fix_cannot_modify_unrelated_source_file(self):
        (self.app / "unrelated.py").write_text("VALUE = 0\n", encoding="utf-8")
        def unrelated_change(engine, stage, *_):
            (stage / "unrelated.py").write_text("VALUE = 1\n", encoding="utf-8")
            return "Wrong file edited"
        with patch.object(workflow, "run_analysis", return_value=self.analysis()), \
             patch.object(workflow, "run_patch", side_effect=unrelated_change):
            outcome = workflow.run_one("test-app")
        self.assertEqual(outcome["applied"], 0)
        self.assertEqual((self.app / "unrelated.py").read_text(), "VALUE = 0\n")

    def test_approve_invalid_id_is_rejected_without_file_access(self):
        with self.assertRaises(ValueError):
            workflow.decide("test-app", "../../outside", True)

    def test_install_shared_links_work_for_project(self):
        repo = self.skill.parent / "other-project"
        repo.mkdir()
        script = Path(__file__).resolve().parents[1] / "scripts/install.py"
        cp = subprocess.run([sys.executable, str(script), "--agent", "both", "--scope", "project",
                             "--project-root", str(repo)], capture_output=True, text=True)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        for dirname in (".agents", ".claude"):
            dest = repo / dirname / "skills" / "ai-app-maintainer"
            self.assertTrue(dest.is_symlink())
            self.assertEqual(dest.resolve(), script.parent.parent)

    def test_suggest_implements_nothing_and_only_records_feature_ux(self):
        output = {"summary": "Possible menu simplification", "overall_health": "healthy",
                  "findings": [issue("feature", "low", "Add compact settings menu"),
                               issue("ux", "low", "Reorganize navigation"),
                               issue("bugfix", "low", "Fix unrelated bug")], "monitor_notes": []}
        with patch.object(workflow, "safe_analysis", return_value=output), \
             patch.object(workflow, "run_patch") as edit:
            result = workflow.suggest_one("test-app")
            edit.assert_not_called()
        self.assertEqual(result["suggestions"], 2)
        self.assertEqual((self.app / "service.py").read_text(), "VALUE = 0\n")
        self.assertEqual(len(list((self.skill / "managed-apps/test-app/proposals").glob("*.json"))), 2)
        self.assertTrue((self.skill / "managed-apps/test-app/latest-suggestions.md").exists())

    def test_suggest_off_never_calls_agent(self):
        self.set_global(upgrade_suggestions=False)
        with patch.object(workflow, "safe_analysis") as agent:
            result = workflow.suggest_one("test-app")
            agent.assert_not_called()
        self.assertEqual(result["status"], "upgrade_suggestions_off")

    def test_safe_analysis_uses_sanitized_stage_only(self):
        (self.app / ".env").write_text("SECRET=private\n", encoding="utf-8")
        (self.app / "logs/app.log").write_text("secret token in source logs\n", encoding="utf-8")
        (self.app / ".hidden").mkdir(exist_ok=True)
        (self.app / ".hidden" / "key").write_text("private", encoding="utf-8")
        def fake_analysis(engine, cwd, prompt, timeout):
            self.assertNotEqual(cwd, self.app)
            self.assertTrue((cwd / "service.py").exists())
            self.assertFalse((cwd / ".env").exists())
            self.assertFalse((cwd / "logs/app.log").exists())
            self.assertFalse((cwd / ".hidden").exists())
            self.assertTrue("some prompt" in prompt)
            return self.analysis()
        with patch.object(workflow, "run_analysis", side_effect=fake_analysis):
            result = workflow.safe_analysis("codex", self.app, "some prompt", 60)
        self.assertIn("findings", result)

    def test_help_is_description_only_and_upgrade_topic_works(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            rc = maintainer.main(["help", "업그레이드", "제안은", "어떻게", "해?"])
        self.assertEqual(rc, 0)
        self.assertIn("suggest --app", output.getvalue())
        self.assertEqual((self.app / "service.py").read_text(), "VALUE = 0\n")
        self.assertFalse(list((self.skill / "managed-apps/test-app/inspections").glob("*")))

    def test_approval_required_for_important_change(self):
        changed = issue("bugfix", "high", "Major state schema change", severity="high")
        with patch.object(workflow, "run_analysis", return_value=self.analysis(changed)), \
             patch.object(workflow, "run_patch") as edit:
            result = workflow.run_one("test-app")
            edit.assert_not_called()
        self.assertEqual(result["applied"], 0)
        p = core.load_json(next((self.skill / "managed-apps/test-app/proposals").glob("*.json")))
        self.assertEqual(p["status"], "pending_approval")

    def test_rollback_on_post_apply_verification_failure(self):
        output = self.analysis()
        original_tests = workflow.run_tests
        calls = [0]
        def flaky_test(root, cmds, timeout):
            calls[0] += 1
            if calls[0] == 2:
                raise RuntimeError("Post-deploy style smoke check failed")
            return original_tests(root, cmds, timeout)
        with patch.object(workflow, "run_analysis", return_value=output), \
             patch.object(workflow, "run_patch", side_effect=self.patch_code), \
             patch.object(workflow, "run_tests", side_effect=flaky_test):
            result = workflow.run_one("test-app")
        self.assertEqual(result["applied"], 0)
        self.assertEqual((self.app / "service.py").read_text(), "VALUE = 0\n")
        self.assertTrue(any(p.get("status") == "rolled_back" for p in [
            core.load_json(p) for p in (self.skill / "managed-apps/test-app/fixes").glob("*.json")]))

    def test_followup_logs_not_counted_twice(self):
        with patch.object(workflow, "run_analysis", return_value=self.analysis()), \
             patch.object(workflow, "run_patch", side_effect=self.patch_code):
            workflow.run_one("test-app")
        # A post-fix normal event (without the original error marker)
        event_at = core.stamp(core.now() + timedelta(seconds=2))
        with self.log.open("a", encoding="utf-8") as f:
            f.write(event_at + " INFO request completed cleanly\n")
        nothing = {"summary": "No new findings", "overall_health": "healthy", "findings": [], "monitor_notes": []}
        with patch.object(workflow, "run_analysis", return_value=nothing):
            workflow.run_one("test-app")
            first = workflow.read_monitors("test-app")[0]
            workflow.run_one("test-app")
            second = workflow.read_monitors("test-app")[0]
        self.assertEqual(first["verified_observation_count"], 1)
        self.assertEqual(second["verified_observation_count"], 1)

    def test_upgrade_suggestions_off(self):
        self.set_global(upgrade_suggestions=False)
        with patch.object(workflow, "run_analysis", return_value=self.analysis(issue("ux", "low", "Restructure menu"))):
            result = workflow.run_one("test-app")
        self.assertEqual(result["findings"], 0)
        self.assertFalse(list((self.skill / "managed-apps/test-app/proposals").glob("*.json")))

    def test_critical_paths_never_auto_apply(self):
        (self.app / "auth.py").write_text("VALUE = 0\n")
        finding = issue(title="Repair auth failure")
        finding["file_hints"] = ["auth.py"]
        def change_auth(engine, stage, *_):
            (stage / "auth.py").write_text("VALUE = 1\n")
            return "modified"
        with patch.object(workflow, "run_analysis", return_value=self.analysis(finding)), \
             patch.object(workflow, "run_patch", side_effect=change_auth):
            result = workflow.run_one("test-app")
        self.assertEqual(result["applied"], 0)
        self.assertEqual((self.app / "auth.py").read_text(), "VALUE = 0\n")
        proposal = core.load_json(next((self.skill / "managed-apps/test-app/proposals").glob("*.json")))
        self.assertEqual(proposal["status"], "pending_approval")

    def test_failed_test_prevents_change(self):
        reg = core.registry()
        reg["apps"]["test-app"]["test_commands"] = [[sys.executable, "-c", "raise SystemExit(5)"]]
        core.atomic_json(core.REGISTRY, reg)
        with patch.object(workflow, "run_analysis", return_value=self.analysis()), \
             patch.object(workflow, "run_patch", side_effect=self.patch_code):
            result = workflow.run_one("test-app")
        self.assertEqual(result["applied"], 0)
        self.assertEqual((self.app / "service.py").read_text(), "VALUE = 0\n")

    def test_no_test_auto_not_eligible(self):
        reg = core.registry()
        reg["apps"]["test-app"]["test_commands"] = []
        core.atomic_json(core.REGISTRY, reg)
        with patch.object(workflow, "run_analysis", return_value=self.analysis()), \
             patch.object(workflow, "run_patch") as edit:
            workflow.run_one("test-app")
            edit.assert_not_called()

    def test_auto_setting_recalculated_for_existing_proposal(self):
        with patch.object(workflow, "run_analysis", return_value=self.analysis()), \
             patch.object(workflow, "run_patch", side_effect=RuntimeError("Temporary model error")):
            workflow.run_one("test-app")
        self.set_global(auto_fix=False)
        with patch.object(workflow, "run_analysis", return_value=self.analysis()), \
             patch.object(workflow, "run_patch") as edit:
            workflow.run_one("test-app")
            edit.assert_not_called()
        p = core.load_json(next((self.skill / "managed-apps/test-app/proposals").glob("*.json")))
        self.assertEqual(p["status"], "pending_approval")


if __name__ == "__main__":
    unittest.main()
