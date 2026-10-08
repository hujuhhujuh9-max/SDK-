"""Exercise fail-closed build provenance and actual acceptance receipt checks."""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.check_apk_artifact import validate_build_run, verify_host_acceptance
from scripts.check_device_acceptance import REQUIRED_CHECKS, REQUIRED_RECEIPTS, evidence_hashes, verify_acceptance
from scripts.startup_config import parse_startup_config, startup_config


class StartupConfigTests(unittest.TestCase):
    def test_default_and_selected_app_have_explicit_distinct_routes(self):
        self.assertEqual(startup_config(), {"schema_version": 1, "mode": "story", "initial_route": "/"})
        self.assertEqual(parse_startup_config(json.dumps(startup_config("app")))["initial_route"], "/records")

    def test_unknown_modes_and_mismatched_routes_are_rejected(self):
        for mode in (None, "APP", "other", [], {}):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                startup_config(mode)
        for config in ({}, [], dict(startup_config("app"), initial_route="/"),
                       dict(startup_config(), schema_version=0), dict(startup_config(), schema_version=True)):
            with self.subTest(config=config), self.assertRaises(ValueError):
                parse_startup_config(json.dumps(config))


class BuildRunTests(unittest.TestCase):
    def setUp(self):
        self.run = {"id": 123, "status": "completed", "conclusion": "success",
                    "repository": {"full_name": "owner/sdk"}, "head_sha": "a" * 40,
                    "path": ".github/workflows/build-android.yml"}

    def test_completed_successful_build_is_identified_by_its_source(self):
        self.assertEqual(validate_build_run(self.run, "owner/sdk"), "a" * 40)

    def test_failed_cancelled_skipped_wrong_workflow_and_unidentified_runs_are_rejected(self):
        for change in ({"conclusion": "failure"}, {"conclusion": "cancelled"}, {"conclusion": "skipped"},
                       {"status": "in_progress", "conclusion": None}, {"path": ".github/workflows/check-runtime.yml"},
                       {"repository": {"full_name": "other/sdk"}}, {"head_sha": "unknown"}):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                validate_build_run(dict(self.run, **change), "owner/sdk", current_run_id=123)

    def test_dependent_device_job_can_read_only_its_own_running_integration_build(self):
        for status in ("in_progress", "pending", "queued"):
            run = dict(self.run, status=status, conclusion=None,
                       path=".github/workflows/integration-startup.yml")
            self.assertEqual(validate_build_run(run, "owner/sdk", 123), "a" * 40)
            for current in (None, 456):
                with self.subTest(status=status, current=current), self.assertRaises(RuntimeError):
                    validate_build_run(run, "owner/sdk", current)

    def test_empty_skipped_failed_or_wrong_source_host_suites_cannot_accept_an_apk(self):
        receipt = {"source_sha": "a" * 40, "status": "passed", "tests_run": 250,
                   "skipped": 0, "failures": 0, "errors": 0}
        verify_host_acceptance(receipt, "a" * 40)
        for key, value in (("source_sha", "b" * 40), ("status", "failed"), ("tests_run", 0),
                           ("tests_run", True), ("skipped", 1), ("failures", 1), ("errors", 1)):
            with self.subTest(field=key), self.assertRaisesRegex(RuntimeError, "without skips"):
                verify_host_acceptance(dict(receipt, **{key: value}), "a" * 40)


class DeviceAcceptanceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name)
        for name in REQUIRED_RECEIPTS:
            self.write(name, {"exercised": True})
        self.write("apk-inspection.json", {"sha256": "b" * 64, "startup_mode": "app"})
        self.write("startup.json", {"mode": "app", "initial_route": "/records", "pid": 123})
        self.write("diagnostics.json", {"errors": {}})
        self.receipt = {"status": "passed", "startup_mode": "app", "source_sha": "a" * 40,
                        "skipped": [], "checks": list(REQUIRED_CHECKS), "apk_sha256": "b" * 64,
                        "receipts": evidence_hashes(self.output)}
        self.write("acceptance.json", self.receipt)

    def write(self, name, value):
        (self.output / name).write_text(json.dumps(value))

    def test_complete_receipts_match_the_accepted_apk_mode_and_source(self):
        self.assertEqual(verify_acceptance(self.output, "app", "a" * 40), self.receipt)
        for mode, source in (("story", "a" * 40), ("app", "c" * 40)):
            with self.subTest(mode=mode, source=source), self.assertRaises(RuntimeError):
                verify_acceptance(self.output, mode, source)

    def test_skipped_or_missing_phases_cannot_report_success(self):
        for change in ({"status": "failed"}, {"skipped": ["startup"]},
                       {"checks": list(REQUIRED_CHECKS[:-1])}, {"apk_sha256": "c" * 64}):
            self.write("acceptance.json", dict(self.receipt, **change))
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                verify_acceptance(self.output, "app", "a" * 40)

    def test_changed_or_missing_evidence_invalidates_an_old_success_receipt(self):
        self.write("records-persistence.json", {"changed": True})
        with self.assertRaisesRegex(RuntimeError, "evidence changed"):
            verify_acceptance(self.output, "app", "a" * 40)
        (self.output / "records-persistence.json").unlink()
        with self.assertRaises(FileNotFoundError):
            verify_acceptance(self.output, "app", "a" * 40)


if __name__ == "__main__":
    unittest.main()
