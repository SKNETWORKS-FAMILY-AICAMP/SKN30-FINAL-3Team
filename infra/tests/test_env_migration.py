"""Offline private environment migration: preserve provider credentials."""

from __future__ import annotations

import json
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import env_doctor


class OpenAiMigrationTests(unittest.TestCase):
    def migration_root(self, directory):
        root = Path(directory)
        subprocess.run(
            ["git", "init", "-q", str(root)], check=True, capture_output=True
        )
        (root / ".gitignore").write_text(".env\n.env.migration-backup-*\n")
        path = root / "ai/.env"
        path.parent.mkdir()
        path.write_bytes(
            b"# preserve original\r\nAI_OPENAI_API_KEY=synthetic-openai\r\n"
            b"AI_GENERAL_API_KEY=synthetic-gpu\r\n"
            b"AI_GENERAL_BASE_URL=https://gpu.invalid/v1\r\n"
            b"AI_GENERAL_PROVIDER=vllm\r\nAI_VLLM_LLM_API_KEY=synthetic-f2\r\n"
        )
        return root, path

    def test_explicit_openai_preserves_original_backup_and_removes_gpu_url(self):
        with tempfile.TemporaryDirectory() as directory:
            root, path = self.migration_root(directory)
            original = path.read_bytes()
            checks = env_doctor.inspect(
                root, fix=True, local_provider=env_doctor.LocalProvider.OPENAI
            )
            self.assertFalse(any(check["status"] == "fail" for check in checks))
            backups = list(path.parent.glob(".env.migration-backup-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)
            for private in (path, backups[0]):
                self.assertEqual(stat.S_IMODE(private.stat().st_mode), 0o600)
            active = env_doctor.entries(path.read_text())
            self.assertEqual(active["AI_GENERAL_API_KEY"], "synthetic-openai")
            self.assertEqual(active["AI_GENERAL_PROVIDER"], "openai")
            self.assertEqual(active["AI_VLLM_SLLM_API_KEY"], "synthetic-f2")
            self.assertNotIn("AI_GENERAL_BASE_URL", active)
            self.assertNotIn("AI_OPENAI_API_KEY", active)
            self.assertNotIn("synthetic", json.dumps(checks))
            env_doctor.inspect(
                root, fix=True, local_provider=env_doctor.LocalProvider.OPENAI
            )
            self.assertEqual(list(path.parent.glob(".env.migration-backup-*")), backups)

    def test_explicit_openai_maps_legacy_url_and_requires_known_key(self):
        result, _ = env_doctor.rewrite_openai_inputs(
            "AI_OPENAI_API_KEY=synthetic\nAI_OPENAI_BASE_URL=https://openai.invalid/v1\n",
            "",
            env_doctor.LocalProvider.OPENAI,
        )
        self.assertEqual(
            env_doctor.entries(result)["AI_GENERAL_BASE_URL"],
            "https://openai.invalid/v1",
        )
        with self.assertRaises(ValueError):
            env_doctor.rewrite_openai_inputs(
                "AI_OPENAI_BASE_URL=\nAI_GENERAL_API_KEY=synthetic-gpu\n",
                "",
                env_doctor.LocalProvider.OPENAI,
            )

    def test_backup_must_be_ignored_before_any_secret_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root, path = self.migration_root(directory)
            (root / ".gitignore").write_text(".env\n")
            original = path.read_bytes()
            checks = env_doctor.inspect(
                root, fix=True, local_provider=env_doctor.LocalProvider.OPENAI
            )
            self.assertTrue(any(check["status"] == "fail" for check in checks))
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(path.parent.glob(".env.migration-backup-*")), [])

    def test_backup_collision_never_overwrites_or_modifies_active_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root, path = self.migration_root(directory)
            original = path.read_bytes()
            backup = path.with_name(".env.migration-backup-fixed")
            backup.write_text("previous backup")
            with (
                patch.object(env_doctor.secrets, "token_hex", return_value="fixed"),
                self.assertRaises(FileExistsError),
            ):
                env_doctor.inspect(
                    root, fix=True, local_provider=env_doctor.LocalProvider.OPENAI
                )
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(backup.read_text(), "previous backup")

    def test_failed_atomic_replace_keeps_original_and_complete_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root, path = self.migration_root(directory)
            original = path.read_bytes()
            with (
                patch.object(
                    env_doctor.os, "replace", side_effect=OSError("simulated")
                ),
                self.assertRaises(OSError),
            ):
                env_doctor.inspect(
                    root, fix=True, local_provider=env_doctor.LocalProvider.OPENAI
                )
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(
                next(path.parent.glob(".env.migration-backup-*")).read_bytes(), original
            )

    def test_failed_backup_removes_partial_file_and_leaves_original(self):
        with tempfile.TemporaryDirectory() as directory:
            root, path = self.migration_root(directory)
            original = path.read_bytes()
            with (
                patch.object(env_doctor.os, "fsync", side_effect=OSError("simulated")),
                self.assertRaises(OSError),
            ):
                env_doctor.inspect(
                    root, fix=True, local_provider=env_doctor.LocalProvider.OPENAI
                )
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(path.parent.glob(".env.migration-backup-*")), [])

    def test_explicit_migration_still_rejects_duplicate_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root, path = self.migration_root(directory)
            with path.open("a") as stream:
                stream.write("AI_GENERAL_API_KEY=synthetic-other\n")
            original = path.read_bytes()
            checks = env_doctor.inspect(
                root, fix=True, local_provider=env_doctor.LocalProvider.OPENAI
            )
            self.assertTrue(any(check["status"] == "fail" for check in checks))
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(path.parent.glob(".env.migration-backup-*")), [])

    def test_explicit_provider_requires_fix_and_supported_choice(self):
        with self.assertRaises(ValueError):
            env_doctor.inspect(
                Path("unused"), local_provider=env_doctor.LocalProvider.OPENAI
            )
        with self.assertRaises(ValueError):
            env_doctor.inspect(Path("unused"), fix=True, local_provider="vllm")

    def test_rename_preserves_quotes_comments_and_line_endings(self):
        original = (
            'AI_OPENAI_API_KEY="synthetic key" # comment\r\nAI_OPENAI_BASE_URL=\r\n'
        )
        result, changes = env_doctor.rewrite_openai_inputs(original, "")
        self.assertEqual(result, original.replace("AI_OPENAI_", "AI_GENERAL_"))
        self.assertEqual(len(changes), 2)

    def test_equal_inputs_consolidate_without_changing_general(self):
        original = (
            'AI_OPENAI_API_KEY="synthetic"\nAI_GENERAL_API_KEY=synthetic # keep\n'
        )
        result, _ = env_doctor.rewrite_openai_inputs(original, "")
        self.assertEqual(result, "AI_GENERAL_API_KEY=synthetic # keep\n")
        self.assertEqual(env_doctor.rewrite_openai_inputs(result, ""), (result, []))

    def test_distinct_inputs_including_blank_are_never_selected(self):
        for old, new in (("synthetic-old", "synthetic-new"), ("", "synthetic-new")):
            with self.subTest(old_present=bool(old)):
                with self.assertRaises(ValueError) as caught:
                    env_doctor.rewrite_openai_inputs(
                        f"AI_OPENAI_API_KEY={old}\nAI_GENERAL_API_KEY={new}\n", ""
                    )
                self.assertNotIn("synthetic", str(caught.exception))
                self.assertIn("자동 이전하지 않습니다", str(caught.exception))

    def test_provider_is_file_selection_not_ambient_process(self):
        with patch.dict("os.environ", {"AI_GENERAL_PROVIDER": "vllm"}):
            result, _ = env_doctor.rewrite_openai_inputs(
                "AI_OPENAI_API_KEY=synthetic\n", ""
            )
        self.assertIn("AI_GENERAL_API_KEY", result)
        with self.assertRaises(ValueError):
            env_doctor.rewrite_openai_inputs(
                "AI_GENERAL_PROVIDER=vllm\nAI_OPENAI_API_KEY=synthetic\n",
                "AI_GENERAL_PROVIDER=openai\n",
            )

    def test_non_openai_or_invalid_provider_cannot_migrate(self):
        for provider in ("vllm", "llama_cpp", "bedrock", "INVALID", ""):
            with (
                self.subTest(provider=provider),
                self.assertRaises(ValueError) as caught,
            ):
                env_doctor.rewrite_openai_inputs(
                    "AI_OPENAI_API_KEY=synthetic\n", f"AI_GENERAL_PROVIDER={provider}\n"
                )
            self.assertNotIn("synthetic", str(caught.exception))

    def test_duplicate_and_multiline_inputs_are_rejected(self):
        for text in (
            "AI_OPENAI_API_KEY=synthetic\nAI_OPENAI_API_KEY=synthetic\n",
            "AI_OPENAI_API_KEY=synthetic\nAI_GENERAL_API_KEY=a\nAI_GENERAL_API_KEY=b\n",
            "AI_OPENAI_API_KEY=synthetic\nAI_GENERAL_PROVIDER=openai\nAI_GENERAL_PROVIDER=vllm\n",
            'AI_OPENAI_API_KEY="synthetic\nmultiline"\n',
        ):
            with (
                self.subTest(case=text.split("=", 1)[0]),
                self.assertRaises(ValueError),
            ):
                env_doctor.rewrite_openai_inputs(text, "")

    def test_conflict_leaves_whole_file_unchanged_and_redacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "ai/.env"
            path.parent.mkdir()
            original = (
                "AI_VLLM_LLM_API_KEY=synthetic-f2\n"
                "AI_OPENAI_API_KEY=synthetic-openai\n"
                "AI_GENERAL_API_KEY=synthetic-gpu\n"
            )
            path.write_text(original)
            with patch.object(env_doctor, "tracked", return_value=False):
                checks = env_doctor.inspect(root, fix=True)
            self.assertEqual(path.read_text(), original)
            self.assertTrue(any(check["status"] == "fail" for check in checks))
            self.assertNotIn("synthetic", json.dumps(checks))

    def test_dry_run_then_fix_and_infra_file_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in ("ai/.env", "infra/.env", "infra/local/.env"):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    "AI_OPENAI_API_KEY=synthetic\n" if relative == "ai/.env" else ""
                )
                path.chmod(0o644)
            with patch.object(env_doctor, "tracked", return_value=False):
                env_doctor.inspect(root)
                self.assertIn("AI_OPENAI_API_KEY", (root / "ai/.env").read_text())
                env_doctor.inspect(root, fix=True)
            self.assertEqual(
                (root / "ai/.env").read_text(), "AI_GENERAL_API_KEY=synthetic\n"
            )
            for relative in ("ai/.env", "infra/.env", "infra/local/.env"):
                self.assertEqual(stat.S_IMODE((root / relative).stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
