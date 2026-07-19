import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "skill_update.py"
SPEC = importlib.util.spec_from_file_location("skill_update_tested", SCRIPT)
skill_update = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(skill_update)

PET_SCRIPT = ROOT / "scripts" / "pet_club.py"
PET_SPEC = importlib.util.spec_from_file_location("pet_club_updated", PET_SCRIPT)
pet_club = importlib.util.module_from_spec(PET_SPEC)
assert PET_SPEC.loader is not None
PET_SPEC.loader.exec_module(pet_club)


def release_zip(extra: dict[str, bytes] | None = None) -> bytes:
    files = {
        "SKILL.md": b"---\nname: codex-pet-club\ndescription: test\n---\n",
        "agents/openai.yaml": b"interface: {}\n",
        "references/api.md": b"# API\n",
        "scripts/pet_club.py": b'SKILL_VERSION = "9.9.9"\n',
        "scripts/skill_update.py": b"def update():\n    return True\n",
    }
    files.update(extra or {})
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in files.items():
            archive.writestr(name, value)
    return buffer.getvalue()


def manifest(raw: bytes, version: str = "0.4.3") -> dict:
    return {
        "schemaVersion": 1,
        "version": version,
        "archiveUrl": (
            "https://github.com/javaC2RenXiangjie/codex-pet-club-skill/releases/"
            f"download/v{version}/codex-pet-club-skill-v{version}.zip"
        ),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "sizeBytes": len(raw),
        "publishedAt": "2026-07-20T00:00:00Z",
    }


class ManifestTests(unittest.TestCase):
    def test_semantic_versions_compare_numerically(self):
        self.assertGreater(skill_update.parse_version("0.10.0"), skill_update.parse_version("0.9.9"))
        with self.assertRaises(skill_update.UpdateError):
            skill_update.parse_version("v0.4.3")

    def test_manifest_requires_matching_official_release_and_hash(self):
        raw = release_zip()
        accepted = skill_update.validate_manifest(manifest(raw))
        self.assertEqual(accepted["version"], "0.4.3")

        bad_url = manifest(raw)
        bad_url["archiveUrl"] = "https://example.com/codex-pet-club-skill-v0.4.3.zip"
        with self.assertRaisesRegex(skill_update.UpdateError, "official GitHub release"):
            skill_update.validate_manifest(bad_url)

        bad_hash = manifest(raw)
        bad_hash["sha256"] = "A" * 64
        with self.assertRaisesRegex(skill_update.UpdateError, "SHA-256"):
            skill_update.validate_manifest(bad_hash)


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_rejects_path_traversal(self):
        raw = release_zip({"../outside.txt": b"bad"})
        with self.assertRaisesRegex(skill_update.UpdateError, "unsafe release archive path"):
            skill_update.extract_and_validate(raw, self.root / "target")
        self.assertFalse((self.root / "outside.txt").exists())

    def test_rejects_symbolic_links(self):
        buffer = io.BytesIO(release_zip())
        with zipfile.ZipFile(buffer) as source:
            entries = [(info.filename, source.read(info)) for info in source.infolist()]
        rebuilt = io.BytesIO()
        with zipfile.ZipFile(rebuilt, "w") as archive:
            for name, value in entries:
                archive.writestr(name, value)
            link = zipfile.ZipInfo("link")
            link.create_system = 3
            link.external_attr = 0o120777 << 16
            archive.writestr(link, "SKILL.md")
        with self.assertRaisesRegex(skill_update.UpdateError, "symbolic link"):
            skill_update.extract_and_validate(rebuilt.getvalue(), self.root / "target")


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.previous_home = os.environ.get("CODEX_HOME")
        os.environ["CODEX_HOME"] = str(self.root)
        self.installed = self.root / "skills" / "codex-pet-club"
        self.installed.mkdir(parents=True)
        (self.installed / "old.txt").write_text("old", encoding="utf-8")
        config = self.root / "pet-club" / "config.json"
        config.parent.mkdir(parents=True)
        config.write_text('{"key":"preserved-outside-skill"}\n', encoding="utf-8")

    def tearDown(self):
        if self.previous_home is None:
            os.environ.pop("CODEX_HOME", None)
        else:
            os.environ["CODEX_HOME"] = self.previous_home
        self.temporary.cleanup()

    def test_success_replaces_install_without_retaining_old_version(self):
        skill_update.install_release(release_zip(), self.installed)
        self.assertTrue((self.installed / "scripts" / "pet_club.py").is_file())
        self.assertFalse((self.installed / "old.txt").exists())
        self.assertEqual(
            (self.root / "pet-club" / "config.json").read_text(encoding="utf-8"),
            '{"key":"preserved-outside-skill"}\n',
        )
        leftovers = [path.name for path in (self.root / "skills").iterdir() if path.name != "codex-pet-club"]
        self.assertEqual(leftovers, [])

    def test_failed_transient_cleanup_rolls_back_old_install(self):
        staged = self.root / "skills" / "staged"
        staged.mkdir()
        (staged / "new.txt").write_text("new", encoding="utf-8")
        real_rmtree = shutil.rmtree

        def selective_rmtree(path, *args, **kwargs):
            if Path(path).name.startswith(".codex-pet-club-updating-old-"):
                raise OSError("simulated lock")
            return real_rmtree(path, *args, **kwargs)

        with patch.object(skill_update.shutil, "rmtree", side_effect=selective_rmtree), self.assertRaisesRegex(
            skill_update.UpdateError,
            "update was rolled back",
        ):
            skill_update.replace_install(self.installed, staged)
        self.assertEqual((self.installed / "old.txt").read_text(encoding="utf-8"), "old")
        leftovers = [path.name for path in (self.root / "skills").iterdir() if path.name != "codex-pet-club"]
        self.assertEqual(leftovers, [])

    def test_source_checkout_never_self_modifies(self):
        with patch.object(skill_update, "fetch_manifest") as fetch:
            result = skill_update.check_and_apply_update("0.4.3", ROOT)
        self.assertIsNone(result)
        fetch.assert_not_called()


class UpdateDecisionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.previous_home = os.environ.get("CODEX_HOME")
        os.environ["CODEX_HOME"] = str(self.root)
        self.installed = self.root / "skills" / "codex-pet-club"
        self.installed.mkdir(parents=True)

    def tearDown(self):
        if self.previous_home is None:
            os.environ.pop("CODEX_HOME", None)
        else:
            os.environ["CODEX_HOME"] = self.previous_home
        self.temporary.cleanup()

    def test_current_version_does_not_download(self):
        raw = release_zip()
        with patch.object(skill_update, "fetch_manifest", return_value=manifest(raw)), patch.object(
            skill_update,
            "download_archive",
        ) as download:
            result = skill_update.check_and_apply_update("0.4.3", self.installed)
        self.assertIsNone(result)
        download.assert_not_called()

    def test_unavailable_manifest_does_not_block_current_version(self):
        with patch.object(
            skill_update,
            "fetch_manifest",
            side_effect=skill_update.UpdateError("offline"),
        ):
            result = skill_update.check_and_apply_update("0.4.3", self.installed)
        self.assertIsNone(result)

    def test_newer_version_is_installed_and_requests_reload(self):
        raw = release_zip()
        newer = manifest(raw, "0.4.4")
        with patch.object(skill_update, "fetch_manifest", return_value=newer), patch.object(
            skill_update,
            "download_archive",
            return_value=raw,
        ), patch.object(skill_update, "install_release") as install:
            result = skill_update.check_and_apply_update("0.4.3", self.installed)
        install.assert_called_once_with(raw, self.installed)
        self.assertEqual(result, {
            "updated": True,
            "fromVersion": "0.4.3",
            "toVersion": "0.4.4",
            "restartRequired": True,
        })


class CliBootstrapTests(unittest.TestCase):
    def test_update_stops_current_command_and_requests_next_turn(self):
        update = {
            "updated": True,
            "fromVersion": "0.4.2",
            "toVersion": "0.4.3",
            "restartRequired": True,
        }
        with patch.object(pet_club, "maybe_auto_update", return_value=update), patch.object(
            pet_club,
            "command_list",
        ) as listing, patch("sys.stdout", new_callable=io.StringIO) as stdout:
            exit_code = pet_club.main(["list"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(stdout.getvalue()), update)
        listing.assert_not_called()

    def test_every_normal_command_checks_for_update_first(self):
        with patch.object(pet_club, "maybe_auto_update", return_value=None) as update, patch(
            "sys.stdout", new_callable=io.StringIO
        ) as stdout:
            exit_code = pet_club.main(["version"])
        self.assertEqual(exit_code, 0)
        update.assert_called_once_with()
        self.assertEqual(json.loads(stdout.getvalue())["version"], "0.4.3")


if __name__ == "__main__":
    unittest.main()
