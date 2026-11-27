import tempfile
import unittest
from pathlib import Path

from book_tool_paths import resolve_app_paths


class ResolveAppPathsTests(unittest.TestCase):
    def test_source_checkout_uses_repository_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            module = root / "experiments" / "ruvoice-stress-dictionary" / "build_book_dictionary.py"
            repo_root, workflow_dir = resolve_app_paths(module, frozen=False)
            self.assertEqual(repo_root, root)
            self.assertEqual(workflow_dir, module.parent)

    def test_frozen_build_uses_pyinstaller_bundle_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp)
            repo_root, workflow_dir = resolve_app_paths(
                Path("build_book_dictionary.py"),
                frozen=True,
                bundle_root=bundle,
            )
            self.assertEqual(repo_root, bundle.resolve())
            self.assertEqual(
                workflow_dir,
                bundle.resolve() / "experiments" / "ruvoice-stress-dictionary",
            )

    def test_frozen_build_requires_bundle_root(self):
        with self.assertRaises(RuntimeError):
            resolve_app_paths(Path("module.py"), frozen=True, bundle_root=None)


if __name__ == "__main__":
    unittest.main()
