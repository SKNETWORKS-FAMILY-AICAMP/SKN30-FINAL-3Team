import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from general_runtime import build_command
from model_profiles import load_profile, verify_weights


class ModelProfiles(unittest.TestCase):
    def test_profiles_select_independent_model_revision_and_loader(self):
        for name in ("qwen3-14b-awq", "qwen3-32b-awq", "qwen38-27b-bnb"):
            profile = load_profile(name)
            command = build_command("/models/general", name)
            for flag, expected in (
                ("--served-model-name", profile["model"]),
                ("--revision", profile["revision"]),
                ("--quantization", profile["quantization"]),
                ("--load-format", profile["load_format"]),
            ):
                self.assertEqual(command[command.index(flag) + 1], expected)
            self.assertEqual(command[command.index("--max-model-len") + 1], "8192")
            self.assertEqual(command[command.index("--max-num-seqs") + 1], "1")

    def test_unknown_profile_fails_closed(self):
        with self.assertRaises(ValueError):
            load_profile("arbitrary-model")

    def test_actual_weight_bytes_are_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            weight = path / "model.safetensors"
            weight.write_bytes(b"synthetic")
            profile = {
                "weights": [
                    {
                        "name": weight.name,
                        "size": 9,
                        "sha256": hashlib.sha256(b"synthetic").hexdigest(),
                    }
                ]
            }
            self.assertEqual(len(verify_weights(path, profile)), 64)
            weight.write_bytes(b"different")
            with self.assertRaises(ValueError):
                verify_weights(path, profile)
