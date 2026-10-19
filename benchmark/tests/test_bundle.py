import importlib.util
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "materialize_sdk", Path(__file__).parents[1] / "scripts/materialize_sdk.py"
)
bundle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bundle)


class BundleTests(unittest.TestCase):
    def test_deployed_sdk_does_not_depend_on_local_editable_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, target = root / "source", root / "python_modules"
            (source / "workers").mkdir(parents=True)
            target.mkdir()
            (source / "workers/__init__.py").write_text("# SDK")
            (source / "workers/bridge.js").write_text("export default {}")
            (source / "_workers_sdk_patch_loader.pth").write_text("import patch_loader")
            (target / "_editable_impl_workers_runtime_sdk.pth").write_text("/local/path")
            bundle.materialize(source, target)
            self.assertTrue((target / "workers/__init__.py").exists())
            self.assertTrue((target / "workers/bridge.js").exists())
            self.assertTrue((target / "_workers_sdk_patch_loader.pth").exists())
            self.assertFalse((target / "_editable_impl_workers_runtime_sdk.pth").exists())
