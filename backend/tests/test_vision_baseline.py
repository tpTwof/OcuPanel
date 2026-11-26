"""Artifact hashes and model/processor revisions must identify the same baseline."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))
from freeze_vision_baseline import freeze
from modules.vision.utils.runtime import clear_model_cache, load_model


class BaselineTests(unittest.TestCase):
    def test_processor_and_weights_share_revision_and_cache_is_versioned(self):
        clear_model_cache()
        self.addCleanup(clear_model_cache)
        model_type = Mock()
        with patch("modules.vision.utils.runtime.AutoImageProcessor.from_pretrained") as processor:
            load_model("model", model_type, "cpu", revision="a" * 40)
            load_model("model", model_type, "cpu", revision="a" * 40)
            load_model("model", model_type, "cpu", revision="b" * 40)
        self.assertEqual(processor.call_count, 2)
        processor.assert_any_call("model", revision="a" * 40, use_fast=False)
        model_type.from_pretrained.assert_any_call("model", revision="a" * 40)
        model_type.from_pretrained.assert_any_call("model", revision="b" * 40)

    def test_artifacts_are_hashed_and_floating_revisions_rejected(self):
        description = json.loads((ROOT / "docs/baselines/baseline-description.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "weights.bin").write_bytes(b"baseline")
            result = freeze(root, description)
            self.assertEqual(result["artifacts"][0]["sha256"], hashlib.sha256(b"baseline").hexdigest())
            with self.assertRaisesRegex(ValueError, "pinned"):
                freeze(root, {**description, "classification_revision": "main"})


if __name__ == "__main__":
    unittest.main()
