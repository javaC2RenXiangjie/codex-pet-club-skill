import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "pet_club.py"
SPEC = importlib.util.spec_from_file_location("pet_club", SCRIPT)
pet_club = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(pet_club)


class InstalledStateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.previous_home = os.environ.get("CODEX_HOME")
        os.environ["CODEX_HOME"] = self.temporary.name

    def tearDown(self):
        if self.previous_home is None:
            os.environ.pop("CODEX_HOME", None)
        else:
            os.environ["CODEX_HOME"] = self.previous_home
        self.temporary.cleanup()

    def test_records_and_clears_installed_catalog_version(self):
        result = {
            "petKey": "test-pet",
            "name": "Test Pet",
            "installedPath": str(Path(self.temporary.name) / "pets" / "test-pet"),
        }
        state_path = pet_club.save_install_record(
            result,
            "test-pet-0001",
            "1.2.3",
            "a" * 64,
        )
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["schemaVersion"], 1)
        self.assertEqual(state["pets"]["test-pet"]["version"], "1.2.3")
        self.assertEqual(state["pets"]["test-pet"]["catalogId"], "test-pet-0001")

        self.assertTrue(pet_club.clear_install_record("test-pet"))
        self.assertEqual(pet_club.load_installed()["pets"], {})

    def test_missing_state_is_an_empty_versioned_registry(self):
        self.assertEqual(pet_club.load_installed(), {"schemaVersion": 1, "pets": {}})


class SubmissionStatusTests(unittest.TestCase):
    def test_status_queries_submission_endpoint(self):
        submission_id = "9d1ef2a4-55df-4d99-a722-18d1db7cb83a"
        expected = {
            "submission": {
                "id": submission_id,
                "status": "published",
                "reviewNote": "checked",
            }
        }
        args = pet_club.parser().parse_args(["--api", "https://pets.example", "status", submission_id])

        with patch.object(pet_club, "request_json", return_value=expected) as request, patch(
            "sys.stdout", new_callable=io.StringIO
        ) as stdout:
            args.func(args)

        request.assert_called_once_with(
            f"https://pets.example/api/submissions/{submission_id}"
        )
        self.assertEqual(json.loads(stdout.getvalue()), expected)


if __name__ == "__main__":
    unittest.main()
