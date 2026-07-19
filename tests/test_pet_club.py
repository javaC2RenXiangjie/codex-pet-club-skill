import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import zipfile


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "pet_club.py"
SPEC = importlib.util.spec_from_file_location("pet_club", SCRIPT)
pet_club = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(pet_club)


def valid_webp() -> bytes:
    width_minus_one = (pet_club.EXPECTED_ATLAS[0] - 1).to_bytes(3, "little")
    height_minus_one = (pet_club.EXPECTED_ATLAS[1] - 1).to_bytes(3, "little")
    payload = b"\0" * 4 + width_minus_one + height_minus_one
    return b"RIFF" + (22).to_bytes(4, "little") + b"WEBPVP8X" + (10).to_bytes(4, "little") + payload


def bom_manifest() -> bytes:
    manifest = {
        "id": "OrangeWhiteKitty",
        "displayName": "Orange White Kitty",
        "spritesheetPath": "spritesheet.webp",
        "spriteVersionNumber": 2,
    }
    return b"\xef\xbb\xbf" + json.dumps(manifest).encode("utf-8")


class BomManifestTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.previous_home = os.environ.get("CODEX_HOME")
        os.environ["CODEX_HOME"] = self.temporary.name
        self.pet = Path(self.temporary.name) / "source-pet"
        self.pet.mkdir()
        (self.pet / "pet.json").write_bytes(bom_manifest())
        (self.pet / "spritesheet.webp").write_bytes(valid_webp())

    def tearDown(self):
        if self.previous_home is None:
            os.environ.pop("CODEX_HOME", None)
        else:
            os.environ["CODEX_HOME"] = self.previous_home
        self.temporary.cleanup()

    def test_validate_and_pack_accept_bom_and_normalize_package(self):
        validated = pet_club.validate_pet_dir(self.pet)
        self.assertEqual(validated["petKey"], "orangewhitekitty")

        raw, packed = pet_club.pack_pet(self.pet)
        self.assertEqual(packed["petKey"], "orangewhitekitty")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            packaged_manifest = archive.read("pet.json")
        self.assertFalse(packaged_manifest.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(json.loads(packaged_manifest.decode("utf-8"))["id"], "OrangeWhiteKitty")

    def test_install_accepts_bom_package_and_normalizes_local_manifest(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("pet.json", bom_manifest())
            archive.writestr("spritesheet.webp", valid_webp())

        result = pet_club.install_package(buffer.getvalue(), "orangewhitekitty")
        installed_manifest = Path(result["installedPath"]) / "pet.json"
        self.assertFalse(installed_manifest.read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertEqual(json.loads(installed_manifest.read_text(encoding="utf-8"))["id"], "OrangeWhiteKitty")


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


class AccountKeyTests(unittest.TestCase):
    KEY = "cpc_sk_a1b2c3d4_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef"

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.previous_home = os.environ.get("CODEX_HOME")
        self.previous_key = os.environ.pop("CODEX_PET_CLUB_KEY", None)
        os.environ["CODEX_HOME"] = self.temporary.name

    def tearDown(self):
        if self.previous_home is None:
            os.environ.pop("CODEX_HOME", None)
        else:
            os.environ["CODEX_HOME"] = self.previous_home
        if self.previous_key is not None:
            os.environ["CODEX_PET_CLUB_KEY"] = self.previous_key
        self.temporary.cleanup()

    def test_configure_validates_and_saves_key_without_printing_secret(self):
        args = pet_club.parser().parse_args([
            "configure",
            "--api",
            "https://pets.example",
            "--key",
            self.KEY,
        ])
        identity = {
            "user": {
                "id": "user-1",
                "displayName": "Orange Cat",
                "emailMasked": "or****@example.com",
                "emailVerified": True,
            }
        }
        with patch.object(pet_club, "request_json", return_value=identity) as request, patch(
            "sys.stdout", new_callable=io.StringIO
        ) as stdout:
            args.func(args)

        config = pet_club.load_config()
        self.assertEqual(config["api"], "https://pets.example")
        self.assertEqual(config["key"], self.KEY)
        self.assertNotIn(self.KEY, stdout.getvalue())
        self.assertIn("cpc_sk_a1b2c3d4_••••••••", stdout.getvalue())
        request.assert_called_once_with(
            "https://pets.example/api/me",
            headers={"Authorization": f"Bearer {self.KEY}"},
        )

    def test_account_uses_saved_key_and_only_returns_a_preview(self):
        pet_club.save_config({"api": "https://pets.example", "key": self.KEY})
        args = pet_club.parser().parse_args(["account"])
        identity = {"user": {"id": "user-1", "emailMasked": "or****@example.com"}}
        with patch.object(pet_club, "request_json", return_value=identity) as request, patch(
            "sys.stdout", new_callable=io.StringIO
        ) as stdout:
            args.func(args)

        self.assertNotIn(self.KEY, stdout.getvalue())
        self.assertEqual(json.loads(stdout.getvalue())["keyPreview"], "cpc_sk_a1b2c3d4_••••••••")
        request.assert_called_once_with(
            "https://pets.example/api/me",
            headers={"Authorization": f"Bearer {self.KEY}"},
        )

    def test_configure_accepts_key_from_stdin(self):
        args = pet_club.parser().parse_args(["configure", "--key-stdin"])
        identity = {"user": {"id": "user-1", "emailMasked": "or****@example.com"}}
        with patch("sys.stdin", io.StringIO(f"{self.KEY}\n")), patch.object(
            pet_club, "request_json", return_value=identity
        ), patch("sys.stdout", new_callable=io.StringIO) as stdout:
            args.func(args)

        self.assertEqual(pet_club.load_config()["key"], self.KEY)
        self.assertNotIn(self.KEY, stdout.getvalue())

    def test_clear_key_preserves_registry_configuration(self):
        pet_club.save_config({"api": "https://pets.example", "key": self.KEY})
        args = pet_club.parser().parse_args(["configure", "--clear-key"])
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            args.func(args)

        self.assertEqual(pet_club.load_config(), {"api": "https://pets.example"})
        self.assertFalse(json.loads(stdout.getvalue())["keyConfigured"])

    def test_publish_requires_key_and_sends_bearer_authorization(self):
        pet_club.save_config({"api": "https://pets.example", "key": self.KEY})
        args = pet_club.parser().parse_args(["publish", "test-pet"])
        packed = {
            "name": "Test Pet",
            "petKey": "test-pet",
            "manifest": {"description": "", "author": "Tests", "license": "MIT"},
            "sha256": "a" * 64,
        }
        with patch.object(pet_club, "resolve_local", return_value=Path("test-pet")), patch.object(
            pet_club, "pack_pet", return_value=(b"zip", packed)
        ), patch.object(
            pet_club, "multipart", return_value=(b"body", "boundary")
        ), patch.object(
            pet_club, "request_json", return_value={"submission": {"id": "submission-1"}}
        ) as request, patch("sys.stdout", new_callable=io.StringIO):
            args.func(args)

        headers = request.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], f"Bearer {self.KEY}")

    def test_publish_without_key_stops_before_packaging(self):
        args = pet_club.parser().parse_args(["publish", "test-pet"])
        with patch.object(pet_club, "pack_pet") as pack, self.assertRaisesRegex(
            pet_club.ClubError,
            "Skill Key is required",
        ):
            args.func(args)
        pack.assert_not_called()


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

    def test_rate_limit_reports_retry_interval_without_retrying(self):
        error = urllib.error.HTTPError(
            "https://pets.example/api/pets",
            429,
            "Too Many Requests",
            {"Retry-After": "120"},
            io.BytesIO(b'{"error":"limited"}'),
        )
        with patch("urllib.request.urlopen", side_effect=error), self.assertRaisesRegex(
            pet_club.ClubError,
            "Retry after about 120 seconds",
        ):
            pet_club.request_json(
                "https://pets.example/api/pets",
                method="POST",
                body=b"test",
            )


if __name__ == "__main__":
    unittest.main()
