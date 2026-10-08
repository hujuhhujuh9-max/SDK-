"""Source staging must identify A and keep the existing demo/runtime untouched."""

import hashlib
import tempfile
import unittest
from pathlib import Path

from scripts.check_native_story_mailbox import REQUIRED_APIS, recipe_hashes, stage_project, validate_runtime


def runtime_source(root):
    root.mkdir()
    source = "\n".join("def " + name + "():\n    pass\n" for name in REQUIRED_APIS)
    (root / "sdk_bridge.py").write_text(source)
    (root / "renfletpy.py").write_text("# source input\n")
    return source


class NativeStoryMailboxChecksTests(unittest.TestCase):
    def test_legacy_default_bridge_cannot_be_mistaken_for_confirmed_a_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = Path(folder)
            (runtime / "renfletpy.py").write_text("# old story publication runtime\n")
            (runtime / "sdk_bridge.py").write_text("def request_save(): pass\ndef save_status(): pass\n")
            with self.assertRaisesRegex(ValueError, "confirmed A runtime API.*confirm_story_command"):
                validate_runtime(runtime)

    def test_required_bridge_source_is_hashed_without_importing_side_effects(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            runtime = root / "runtime"
            source = runtime_source(runtime)
            with (runtime / "sdk_bridge.py").open("a") as stream:
                stream.write('raise RuntimeError("Do not import during structural validation")\n')
            self.assertEqual(validate_runtime(runtime), hashlib.sha256((runtime / "sdk_bridge.py").read_bytes()).hexdigest())
            (runtime / "sdk_bridge.py").write_text(source.replace("def restore_story_status():", "def old_restore():"))
            with self.assertRaisesRegex(ValueError, "restore_story_status"):
                validate_runtime(runtime)

    def test_missing_runtime_companion_is_an_actionable_input_error(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "sdk_bridge.py").write_text("def request_story(): pass\n")
            with self.assertRaisesRegex(ValueError, "sdk_bridge.py and renfletpy.py"):
                validate_runtime(root)

    def test_staging_copies_actual_runtime_and_only_the_mailbox_host_without_mutations(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            runtime = root / "runtime"
            runtime_source(runtime)
            recipe = root / "recipe"
            (recipe / "game").mkdir(parents=True)
            (recipe / "app").mkdir()
            sources = {"game/story.rpy": "# callable library\n",
                       "game/profile.rpy": "# early profile\n",
                       "game/host.rpy": "# standalone host must not be staged\n",
                       "app/host.rpy": "# mailbox host\n",
                       "app/native_story_mailbox.py": "# module adapter\n"}
            for name, source in sources.items():
                (recipe / name).write_text(source)
            before = {path: path.read_bytes() for path in recipe.rglob("*") if path.is_file()}
            bridge_before = (runtime / "sdk_bridge.py").read_bytes()
            project = stage_project(root, "project", recipe, runtime)
            self.assertEqual((project / "sdk_bridge.py").read_bytes(), bridge_before)
            self.assertEqual((project / "game/zz-host.rpy").read_text(), sources["app/host.rpy"])
            self.assertFalse((project / "game/host.rpy").exists())
            self.assertTrue((project / "game/probe.rpy").is_file())
            self.assertTrue((project / "native_story_mailbox_check.py").is_file())
            self.assertEqual(before, {path: path.read_bytes() for path in before})
            self.assertEqual((runtime / "sdk_bridge.py").read_bytes(), bridge_before)
            expected = {name: hashlib.sha256(text.encode()).hexdigest() for name, text in sources.items()
                        if name != "game/host.rpy"}
            self.assertEqual(recipe_hashes(project), expected)
            source = stage_project(root, "source", recipe, runtime, probe=False)
            self.assertFalse((source / "game/probe.rpy").exists())
            self.assertFalse((source / "native_story_mailbox_check.py").exists())
            self.assertEqual(recipe_hashes(source), expected)
