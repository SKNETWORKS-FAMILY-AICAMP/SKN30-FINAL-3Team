"""Check host probes against the image's public model identity without a GPU."""

import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import general_runtime
import probe


class GeneralProbeTests(unittest.TestCase):
    def test_aws_path_uses_public_served_name_for_status_and_inference(self):
        command = general_runtime.build_command("/models/general")
        self.assertEqual(command[2], "/models/general")
        served = command[command.index("--served-model-name") + 1]
        self.assertEqual(served, general_runtime.MODEL)
        # Terraform supplies this same ID to the AWS host config.
        terraform = (
            Path(__file__).resolve().parents[2] / "environments/dev/serving.tf"
        ).read_text()
        self.assertIn(f'model = "{served}"', terraform)
        requests = []

        def respond(request, timeout):
            requests.append(request)
            self.assertEqual(request.get_header("Authorization"), "Bearer synthetic")
            if request.full_url.endswith("/models"):
                body = {"data": [{"id": served}]}
            elif request.full_url.endswith("/ops/status"):
                body = {"disk_free_bytes": 42}
            else:
                self.assertTrue(request.full_url.endswith("/chat/completions"))
                self.assertEqual(json.loads(request.data)["model"], served)
                body = {"choices": [{"message": {"content": '{"ok":true}'}}]}
            return io.BytesIO(json.dumps(body).encode())

        with patch.object(
            probe.urllib.request, "build_opener", return_value=Mock(open=respond)
        ):
            self.assertEqual(
                probe.read_status("http://127.0.0.1:8000/v1", "synthetic", served),
                {"model_ready": True, "disk_free_bytes": 42},
            )
            probe.probe("http://127.0.0.1:8000/v1", "synthetic", served)
        self.assertEqual(len(requests), 4)

    def test_wrong_model_never_passes_readiness_or_inference(self):
        opener = Mock()
        opener.open.side_effect = lambda *a, **kw: io.BytesIO(
            b'{"data":[{"id":"/models/general"}]}'
        )
        with patch.object(probe.urllib.request, "build_opener", return_value=opener):
            self.assertFalse(
                probe.read_status(
                    "http://localhost/v1", "synthetic", general_runtime.MODEL
                )["model_ready"]
            )
            with self.assertRaisesRegex(ValueError, "expected model"):
                probe.probe("http://localhost/v1", "synthetic", general_runtime.MODEL)

    def test_authentication_failure_is_not_ready(self):
        opener = Mock()
        opener.open.side_effect = urllib.error.HTTPError(
            "http://localhost/v1/models", 401, "unauthorized", {}, None
        )
        with patch.object(probe.urllib.request, "build_opener", return_value=opener):
            for operation in (probe.read_status, probe.probe):
                with self.assertRaises(urllib.error.HTTPError):
                    operation("http://localhost/v1", "synthetic", general_runtime.MODEL)
