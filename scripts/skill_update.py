#!/usr/bin/env python3
"""Secure in-place updater for the official Codex Pet Club Skill install."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import urllib.error
import urllib.request
import uuid
import zipfile


MANIFEST_URL = "https://codex-pet-club.cpc-community.workers.dev/api/skill/version"
OFFICIAL_RELEASE_PATTERN = re.compile(
    r"^https://github\.com/javaC2RenXiangjie/codex-pet-club-skill/releases/download/"
    r"v(?P<tag>\d+\.\d+\.\d+)/codex-pet-club-skill-v(?P<file>\d+\.\d+\.\d+)\.zip$"
)
VERSION_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
MAX_ARCHIVE_BYTES = 5 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 15 * 1024 * 1024
MAX_ARCHIVE_FILES = 64
REQUIRED_FILES = {
    "SKILL.md",
    "agents/openai.yaml",
    "references/api.md",
    "scripts/pet_club.py",
    "scripts/skill_update.py",
}


class UpdateError(RuntimeError):
    """Raised when a newer release cannot be verified or installed safely."""


def parse_version(value: str) -> tuple[int, int, int]:
    match = VERSION_PATTERN.fullmatch(value)
    if not match:
        raise UpdateError(f"invalid semantic version: {value!r}")
    return tuple(int(part) for part in match.groups())


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser().resolve()


def official_install_root() -> Path:
    return codex_home() / "skills" / "codex-pet-club"


def same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left.resolve())) == os.path.normcase(str(right.resolve()))


def fetch_manifest(opener=urllib.request.urlopen) -> dict:
    request = urllib.request.Request(
        MANIFEST_URL,
        method="GET",
        headers={
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "User-Agent": "Codex-Pet-Club-Updater/1",
        },
    )
    try:
        with opener(request, timeout=5) as response:
            raw = response.read(64 * 1024 + 1)
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        raise UpdateError(f"version service unavailable: {exc}") from exc
    if len(raw) > 64 * 1024:
        raise UpdateError("version manifest is unexpectedly large")
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError("version service returned invalid JSON") from exc
    return validate_manifest(manifest)


def validate_manifest(value: object) -> dict:
    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        raise UpdateError("unsupported version manifest")
    version = value.get("version")
    archive_url = value.get("archiveUrl")
    sha256 = value.get("sha256")
    size_bytes = value.get("sizeBytes")
    if not isinstance(version, str):
        raise UpdateError("version manifest is missing version")
    parse_version(version)
    if not isinstance(archive_url, str):
        raise UpdateError("version manifest is missing archiveUrl")
    release = OFFICIAL_RELEASE_PATTERN.fullmatch(archive_url)
    if not release or release.group("tag") != version or release.group("file") != version:
        raise UpdateError("version manifest does not reference the matching official GitHub release")
    if not isinstance(sha256, str) or not SHA256_PATTERN.fullmatch(sha256):
        raise UpdateError("version manifest has an invalid SHA-256")
    if not isinstance(size_bytes, int) or isinstance(size_bytes, bool) or not 0 < size_bytes <= MAX_ARCHIVE_BYTES:
        raise UpdateError("version manifest has an invalid archive size")
    return {
        "schemaVersion": 1,
        "version": version,
        "archiveUrl": archive_url,
        "sha256": sha256,
        "sizeBytes": size_bytes,
        "publishedAt": value.get("publishedAt"),
    }


def download_archive(manifest: dict, opener=urllib.request.urlopen) -> bytes:
    request = urllib.request.Request(
        manifest["archiveUrl"],
        method="GET",
        headers={
            "Accept": "application/zip, application/octet-stream",
            "User-Agent": "Codex-Pet-Club-Updater/1",
        },
    )
    try:
        with opener(request, timeout=30) as response:
            raw = response.read(MAX_ARCHIVE_BYTES + 1)
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        raise UpdateError(f"release download failed: {exc}") from exc
    if len(raw) > MAX_ARCHIVE_BYTES:
        raise UpdateError("release archive exceeds the 5 MiB safety limit")
    if len(raw) != manifest["sizeBytes"]:
        raise UpdateError("release archive size does not match the signed manifest")
    actual = hashlib.sha256(raw).hexdigest()
    if actual != manifest["sha256"]:
        raise UpdateError("release archive SHA-256 does not match the signed manifest")
    return raw


def safe_member_name(name: str) -> PurePosixPath:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        not normalized
        or "\x00" in normalized
        or path.is_absolute()
        or ".." in path.parts
        or any(part in {"", "."} or ":" in part for part in path.parts)
    ):
        raise UpdateError(f"unsafe release archive path: {name}")
    return path


def validate_archive(archive: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, PurePosixPath]]:
    infos = archive.infolist()
    if not infos or len(infos) > MAX_ARCHIVE_FILES:
        raise UpdateError("release archive must contain 1-64 entries")
    total = sum(info.file_size for info in infos)
    if total > MAX_UNCOMPRESSED_BYTES:
        raise UpdateError("release archive expands beyond the 15 MiB safety limit")

    files: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
    seen: set[str] = set()
    for info in infos:
        path = safe_member_name(info.filename)
        mode = (info.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            raise UpdateError("release archive contains a symbolic link")
        if info.is_dir():
            continue
        key = path.as_posix().lower()
        if key in seen:
            raise UpdateError("release archive contains duplicate paths")
        seen.add(key)
        files.append((info, path))

    names = {path.as_posix() for _, path in files}
    missing = REQUIRED_FILES - names
    if missing:
        raise UpdateError(f"release archive is missing required files: {', '.join(sorted(missing))}")
    return files


def extract_and_validate(raw: bytes, destination: Path) -> None:
    archive_path = destination.parent / f".{destination.name}-{uuid.uuid4().hex}.zip"
    archive_path.write_bytes(raw)
    try:
        try:
            with zipfile.ZipFile(archive_path) as archive:
                files = validate_archive(archive)
                destination.mkdir(parents=True, exist_ok=False)
                for info, relative in files:
                    target = destination.joinpath(*relative.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, target.open("wb") as sink:
                        shutil.copyfileobj(source, sink)
        except zipfile.BadZipFile as exc:
            raise UpdateError("release archive is not a valid ZIP") from exc

        for relative in REQUIRED_FILES:
            if not (destination / relative).is_file():
                raise UpdateError(f"release archive did not extract {relative}")
        for relative in ("scripts/pet_club.py", "scripts/skill_update.py"):
            try:
                compile((destination / relative).read_text(encoding="utf-8"), relative, "exec")
            except (OSError, UnicodeDecodeError, SyntaxError) as exc:
                raise UpdateError(f"release contains invalid Python: {relative}") from exc
        skill_text = (destination / "SKILL.md").read_text(encoding="utf-8")
        if "name: codex-pet-club" not in skill_text:
            raise UpdateError("release contains an unexpected SKILL.md")
    finally:
        archive_path.unlink(missing_ok=True)


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def replace_install(installed: Path, staged: Path) -> None:
    installed = installed.resolve()
    parent = installed.parent
    old = parent / f".codex-pet-club-updating-old-{uuid.uuid4().hex}"
    failed_new = parent / f".codex-pet-club-update-failed-{uuid.uuid4().hex}"
    original_cwd = Path.cwd().resolve()
    moved_cwd = _is_within(original_cwd, installed)
    original_relative = original_cwd.relative_to(installed) if moved_cwd else None
    if moved_cwd:
        os.chdir(parent)

    os.replace(installed, old)
    try:
        os.replace(staged, installed)
    except Exception:
        os.replace(old, installed)
        if moved_cwd:
            os.chdir(original_cwd)
        raise

    try:
        shutil.rmtree(old)
    except Exception as cleanup_error:
        try:
            os.replace(installed, failed_new)
            os.replace(old, installed)
            shutil.rmtree(failed_new)
        except Exception as rollback_error:
            raise UpdateError(
                f"could not remove the transient old version or complete rollback: {rollback_error}"
            ) from cleanup_error
        raise UpdateError("could not remove the transient old version; the update was rolled back") from cleanup_error
    finally:
        if moved_cwd:
            assert original_relative is not None
            restored_cwd = installed / original_relative
            if restored_cwd.exists():
                os.chdir(restored_cwd)
            else:
                os.chdir(parent)


def install_release(raw: bytes, installed: Path) -> None:
    parent = installed.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging_container = Path(tempfile.mkdtemp(prefix=".codex-pet-club-update-", dir=parent))
    staged = staging_container / "codex-pet-club"
    try:
        extract_and_validate(raw, staged)
        replace_install(installed, staged)
    finally:
        if staging_container.exists():
            shutil.rmtree(staging_container, ignore_errors=True)


def check_and_apply_update(current_version: str, skill_root: Path) -> dict | None:
    """Install a newer official release, or return None without blocking the command."""
    parse_version(current_version)
    installed = official_install_root()
    if not installed.is_dir() or not same_path(skill_root, installed):
        return None
    try:
        manifest = fetch_manifest()
    except UpdateError:
        return None
    if parse_version(manifest["version"]) <= parse_version(current_version):
        return None
    raw = download_archive(manifest)
    install_release(raw, installed)
    return {
        "updated": True,
        "fromVersion": current_version,
        "toVersion": manifest["version"],
        "restartRequired": True,
    }
