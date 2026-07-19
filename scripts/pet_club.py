#!/usr/bin/env python3
"""Safe local/remote manager for Codex Pet Club packages."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile

MAX_PACKAGE_BYTES = 32 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 96 * 1024 * 1024
EXPECTED_ATLAS = (1536, 2288)
DEFAULT_API = "https://codex-pet-club.renxiangjie.workers.dev"
DEFAULT_USER_AGENT = "Codex-Pet-Club-Skill/0.2"


class ClubError(RuntimeError):
    pass


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser().resolve()


def pet_root() -> Path:
    return Path(os.environ.get("CODEX_PETS_DIR", codex_home() / "pets")).expanduser().resolve()


def club_root() -> Path:
    return codex_home() / "pet-club"


def config_path() -> Path:
    return club_root() / "config.json"


def installed_path() -> Path:
    return club_root() / "installed.json"


def atomic_write_json(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".tmp-{uuid.uuid4().hex}")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return path


def load_config() -> dict:
    path = config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ClubError(f"Invalid config file: {path}: {exc}") from exc
    return data if isinstance(data, dict) else {}


def save_config(api: str) -> Path:
    api = normalize_api(api)
    return atomic_write_json(config_path(), {"api": api})


def load_installed() -> dict:
    path = installed_path()
    if not path.exists():
        return {"schemaVersion": 1, "pets": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ClubError(f"Invalid installed-pet state: {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("schemaVersion") != 1 or not isinstance(data.get("pets"), dict):
        raise ClubError(f"Invalid installed-pet state shape: {path}")
    return data


def save_install_record(result: dict, catalog_id: str, version: str | None, sha256: str) -> Path:
    data = load_installed()
    pet_key = result["petKey"]
    data["pets"][pet_key] = {
        "catalogId": catalog_id,
        "displayName": result["name"],
        "version": version,
        "sha256": sha256,
        "installedPath": result["installedPath"],
        "installedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    return atomic_write_json(installed_path(), data)


def clear_install_record(pet_key: str) -> bool:
    data = load_installed()
    if pet_key not in data["pets"]:
        return False
    del data["pets"][pet_key]
    atomic_write_json(installed_path(), data)
    return True


def normalize_api(value: str) -> str:
    parsed = urllib.parse.urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ClubError("Registry URL must be a complete http:// or https:// URL")
    return value.rstrip("/")


def api_base(args: argparse.Namespace) -> str:
    value = args.api or os.environ.get("CODEX_PET_CLUB_API") or load_config().get("api") or DEFAULT_API
    return normalize_api(str(value))


def request_json(url: str, method: str = "GET", body: bytes | None = None, headers: dict | None = None) -> dict:
    request_headers = {"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"}
    request_headers.update(headers or {})
    request = urllib.request.Request(url, data=body, method=method, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(MAX_PACKAGE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        detail = exc.read(4096).decode("utf-8", errors="replace")
        if exc.code == 429:
            retry_after = exc.headers.get("Retry-After")
            suffix = f" Retry after about {retry_after} seconds." if retry_after else " Try again later."
            raise ClubError(f"Registry upload rate limit exceeded.{suffix}") from exc
        raise ClubError(f"Registry returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ClubError(f"Could not reach registry: {exc.reason}") from exc
    if len(raw) > MAX_PACKAGE_BYTES:
        raise ClubError("Registry response is unexpectedly large")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClubError("Registry returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise ClubError("Registry returned an unexpected JSON shape")
    return data


def request_bytes(url: str) -> tuple[bytes, dict[str, str]]:
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "application/zip",
            "X-Codex-Pet-Client": "skill-v1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read(MAX_PACKAGE_BYTES + 1)
            headers = {key.lower(): value for key, value in response.headers.items()}
    except urllib.error.HTTPError as exc:
        raise ClubError(f"Download failed with HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ClubError(f"Could not reach registry: {exc.reason}") from exc
    if len(raw) > MAX_PACKAGE_BYTES:
        raise ClubError("Pet package exceeds 32 MiB")
    return raw, headers


def safe_member_name(name: str) -> PurePosixPath:
    path = PurePosixPath(name.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ClubError(f"Unsafe ZIP member path: {name}")
    if any(part in {"", "."} for part in path.parts):
        raise ClubError(f"Invalid ZIP member path: {name}")
    return path


def package_root(names: list[PurePosixPath]) -> PurePosixPath:
    files = [path for path in names if path.name and not str(path).endswith("/")]
    direct = {path.name for path in files if len(path.parts) == 1}
    if {"pet.json", "spritesheet.webp"}.issubset(direct):
        return PurePosixPath(".")
    top = {path.parts[0] for path in files}
    if len(top) != 1:
        raise ClubError("ZIP must be flat or contain exactly one top-level pet folder")
    return PurePosixPath(next(iter(top)))


def webp_dimensions(data: bytes) -> tuple[int, int]:
    if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise ClubError("spritesheet.webp is not a WebP file")
    offset = 12
    while offset + 8 <= len(data):
        chunk = data[offset : offset + 4]
        size = struct.unpack_from("<I", data, offset + 4)[0]
        payload = offset + 8
        if payload + size > len(data):
            raise ClubError("spritesheet.webp has a truncated chunk")
        if chunk == b"VP8X" and size >= 10:
            width = 1 + int.from_bytes(data[payload + 4 : payload + 7], "little")
            height = 1 + int.from_bytes(data[payload + 7 : payload + 10], "little")
            return width, height
        if chunk == b"VP8L" and size >= 5 and data[payload] == 0x2F:
            bits = int.from_bytes(data[payload + 1 : payload + 5], "little")
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        if chunk == b"VP8 " and size >= 10 and data[payload + 3 : payload + 6] == b"\x9d\x01\x2a":
            width = int.from_bytes(data[payload + 6 : payload + 8], "little") & 0x3FFF
            height = int.from_bytes(data[payload + 8 : payload + 10], "little") & 0x3FFF
            return width, height
        offset = payload + size + (size % 2)
    raise ClubError("Could not read WebP dimensions")


def validate_manifest(manifest: object) -> dict:
    if not isinstance(manifest, dict):
        raise ClubError("pet.json must contain a JSON object")
    if manifest.get("spriteVersionNumber") != 2:
        raise ClubError("pet.json must contain spriteVersionNumber: 2")
    pet_id = manifest.get("id")
    if not isinstance(pet_id, str) or not pet_id.strip():
        raise ClubError("pet.json must contain a non-empty id")
    slugify(pet_id)
    display_name = manifest.get("displayName")
    if not isinstance(display_name, str) or not display_name.strip():
        raise ClubError("pet.json must contain a non-empty displayName")
    if manifest.get("spritesheetPath") != "spritesheet.webp":
        raise ClubError('pet.json must contain spritesheetPath: "spritesheet.webp"')
    return manifest


def validate_pet_dir(path: Path) -> dict:
    path = path.resolve()
    manifest_path = path / "pet.json"
    sheet_path = path / "spritesheet.webp"
    if not manifest_path.is_file() or not sheet_path.is_file():
        raise ClubError("Pet folder must contain pet.json and spritesheet.webp")
    try:
        manifest = validate_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as exc:
        raise ClubError(f"pet.json is invalid JSON: {exc}") from exc
    dimensions = webp_dimensions(sheet_path.read_bytes())
    if dimensions != EXPECTED_ATLAS:
        raise ClubError(f"Expected atlas {EXPECTED_ATLAS[0]}x{EXPECTED_ATLAS[1]}, got {dimensions[0]}x{dimensions[1]}")
    return {
        "path": str(path),
        "name": manifest["displayName"],
        "petKey": slugify(manifest["id"]),
        "manifest": manifest,
        "atlas": dimensions,
    }


def validate_zip(raw: bytes) -> tuple[dict, PurePosixPath, zipfile.ZipFile]:
    if len(raw) > MAX_PACKAGE_BYTES:
        raise ClubError("Pet package exceeds 32 MiB")
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise ClubError("Downloaded package is not a valid ZIP") from exc
    infos = archive.infolist()
    if not infos or len(infos) > 128:
        archive.close()
        raise ClubError("ZIP must contain 1-128 entries")
    total = sum(info.file_size for info in infos)
    if total > MAX_UNCOMPRESSED_BYTES:
        archive.close()
        raise ClubError("ZIP expands beyond the 96 MiB safety limit")
    safe = [safe_member_name(info.filename) for info in infos if not info.is_dir()]
    if len({str(path).lower() for path in safe}) != len(safe):
        archive.close()
        raise ClubError("ZIP contains duplicate paths")
    root = package_root(safe)
    prefix = "" if str(root) == "." else f"{root.as_posix()}/"
    try:
        manifest = validate_manifest(json.loads(archive.read(prefix + "pet.json").decode("utf-8")))
        dimensions = webp_dimensions(archive.read(prefix + "spritesheet.webp"))
    except KeyError as exc:
        archive.close()
        raise ClubError(f"ZIP is missing {exc.args[0]}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        archive.close()
        raise ClubError("ZIP contains an invalid pet.json") from exc
    if dimensions != EXPECTED_ATLAS:
        archive.close()
        raise ClubError(f"Expected atlas {EXPECTED_ATLAS[0]}x{EXPECTED_ATLAS[1]}, got {dimensions[0]}x{dimensions[1]}")
    result = {
        "name": manifest["displayName"],
        "petKey": slugify(manifest["id"]),
        "manifest": manifest,
        "atlas": dimensions,
    }
    return result, root, archive


def slugify(value: str) -> str:
    cleaned = "".join(character.lower() if character.isalnum() else "-" for character in value.strip())
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    if not cleaned or len(cleaned) > 64:
        raise ClubError("Pet slug must be 1-64 letters, digits, or hyphen-separated words")
    return cleaned


def public_id(value: str) -> str:
    value = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,63}", value):
        raise ClubError("Pet ID must be 8-64 letters, digits, underscores, or hyphens")
    return value


def resolve_local(value: str) -> Path:
    candidate = Path(value).expanduser()
    if candidate.exists():
        return candidate.resolve()
    candidate = pet_root() / value
    if candidate.exists():
        return candidate.resolve()
    raise ClubError(f"Local pet not found: {value}")


def pack_pet(path: Path) -> tuple[bytes, dict]:
    result = validate_pet_dir(path)
    buffer = io.BytesIO()
    allowed_names = {"pet.json", "spritesheet.webp", "README.md", "LICENSE", "LICENSE.md", "LICENSE.txt", "preview.png", "preview.webp", "preview.gif"}
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for child in sorted(path.iterdir()):
            if child.is_file() and child.name in allowed_names:
                archive.write(child, arcname=child.name)
    raw = buffer.getvalue()
    if len(raw) > MAX_PACKAGE_BYTES:
        raise ClubError("Packed pet exceeds 32 MiB")
    result["sha256"] = hashlib.sha256(raw).hexdigest()
    result["sizeBytes"] = len(raw)
    return raw, result


def backup_existing(target: Path) -> Path | None:
    if not target.exists():
        return None
    backup_dir = club_root() / "backups" / target.name
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / time.strftime("%Y%m%d-%H%M%S")
    if backup.exists():
        backup = backup.with_name(f"{backup.name}-{uuid.uuid4().hex[:6]}")
    shutil.move(str(target), str(backup))
    return backup


def install_package(raw: bytes, expected_pet_key: str | None = None) -> dict:
    result, root, archive = validate_zip(raw)
    try:
        if expected_pet_key and result["petKey"] != slugify(expected_pet_key):
            raise ClubError(
                f"Package id {result['petKey']} does not match registry petKey {expected_pet_key}"
            )
        pets = pet_root()
        pets.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".pet-club-{result['petKey']}-", dir=pets))
        prefix = "" if str(root) == "." else f"{root.as_posix()}/"
        for info in archive.infolist():
            if info.is_dir():
                continue
            member = safe_member_name(info.filename)
            relative = PurePosixPath(member.as_posix()[len(prefix):]) if prefix and member.as_posix().startswith(prefix) else member
            if prefix and not member.as_posix().startswith(prefix):
                continue
            destination = staging.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, destination.open("wb") as sink:
                shutil.copyfileobj(source, sink)
        validate_pet_dir(staging)
        target = pets / result["petKey"]
        backup = backup_existing(target)
        try:
            os.replace(staging, target)
        except Exception:
            if backup and not target.exists():
                shutil.move(str(backup), str(target))
            raise
        result.update({"installedPath": str(target), "backupPath": str(backup) if backup else None})
        return result
    finally:
        archive.close()


def multipart(package: bytes, metadata: dict) -> tuple[bytes, str]:
    boundary = f"codex-pet-club-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    def add(name: str, value: bytes, filename: str | None = None, content_type: str = "text/plain") -> None:
        disposition = f'form-data; name="{name}"'
        if filename:
            disposition += f'; filename="{filename}"'
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            f"Content-Disposition: {disposition}\r\n".encode(),
            f"Content-Type: {content_type}\r\n\r\n".encode(),
            value,
            b"\r\n",
        ])
    add("metadata", json.dumps(metadata, ensure_ascii=False).encode("utf-8"), content_type="application/json")
    add("package", package, filename="pet.zip", content_type="application/zip")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), boundary


def command_configure(args: argparse.Namespace) -> None:
    path = save_config(args.configure_api)
    print(json.dumps({"api": normalize_api(args.configure_api), "config": str(path)}, ensure_ascii=False))


def command_list(args: argparse.Namespace) -> None:
    data = request_json(f"{api_base(args)}/api/pets")
    pets = data.get("pets", [])
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    if not pets:
        print("No published installable pets yet.")
        return
    for pet in pets:
        version = pet.get("version")
        version_label = f"v{version}" if version else "version unknown"
        print(
            f"{pet.get('id','-'):<38} {pet.get('displayName','-')}  "
            f"[{pet.get('license','unknown')}] {version_label}"
        )


def command_info(args: argparse.Namespace) -> None:
    encoded = urllib.parse.quote(public_id(args.pet_id), safe="")
    print(json.dumps(request_json(f"{api_base(args)}/api/pets/{encoded}"), ensure_ascii=False, indent=2))


def command_install(args: argparse.Namespace) -> None:
    load_installed()
    catalog_id = public_id(args.pet_id)
    encoded = urllib.parse.quote(catalog_id, safe="")
    raw, headers = request_bytes(f"{api_base(args)}/api/pets/{encoded}/package")
    expected = headers.get("x-pet-sha256")
    actual = hashlib.sha256(raw).hexdigest()
    if expected and expected.lower() != actual:
        raise ClubError("Downloaded package checksum does not match the registry")
    expected_pet_key = headers.get("x-pet-key")
    if not expected_pet_key:
        raise ClubError("Registry response is missing x-pet-key")
    version = headers.get("x-pet-version")
    result = install_package(raw, expected_pet_key)
    result["catalogId"] = catalog_id
    result["version"] = version
    result["sha256"] = actual
    result["recordPath"] = str(save_install_record(result, catalog_id, version, actual))
    print(json.dumps(result, ensure_ascii=False, indent=2))


def command_validate(args: argparse.Namespace) -> None:
    result = validate_pet_dir(resolve_local(args.local))
    print(json.dumps({key: value for key, value in result.items() if key != "manifest"}, ensure_ascii=False, indent=2))


def command_pack(args: argparse.Namespace) -> None:
    raw, result = pack_pet(resolve_local(args.local))
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(f".tmp-{uuid.uuid4().hex}")
    temporary.write_bytes(raw)
    os.replace(temporary, output)
    print(json.dumps({"output": str(output), **{key: value for key, value in result.items() if key != "manifest"}}, ensure_ascii=False, indent=2))


def command_publish(args: argparse.Namespace) -> None:
    raw, result = pack_pet(resolve_local(args.local))
    manifest = result["manifest"]
    metadata = {
        "name": result["name"],
        "petKey": result["petKey"],
        "description": manifest.get("description", ""),
        "author": manifest.get("author", ""),
        "license": manifest.get("license", "unspecified"),
        "sha256": result["sha256"],
    }
    body, boundary = multipart(raw, metadata)
    response = request_json(
        f"{api_base(args)}/api/pets",
        method="POST",
        body=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Content-Length": str(len(body))},
    )
    print(json.dumps(response, ensure_ascii=False, indent=2))


def command_status(args: argparse.Namespace) -> None:
    encoded = urllib.parse.quote(public_id(args.submission_id), safe="")
    response = request_json(f"{api_base(args)}/api/submissions/{encoded}")
    print(json.dumps(response, ensure_ascii=False, indent=2))


def command_backups(_: argparse.Namespace) -> None:
    root = club_root() / "backups"
    rows = []
    if root.exists():
        for slug_dir in sorted(root.iterdir()):
            if slug_dir.is_dir():
                for backup in sorted(slug_dir.iterdir(), reverse=True):
                    if backup.is_dir():
                        rows.append({"slug": slug_dir.name, "path": str(backup), "created": backup.name})
    print(json.dumps({"backups": rows}, ensure_ascii=False, indent=2))


def command_installed(_: argparse.Namespace) -> None:
    print(json.dumps(load_installed(), ensure_ascii=False, indent=2))


def command_restore(args: argparse.Namespace) -> None:
    load_installed()
    slug = slugify(args.slug)
    if args.backup:
        backup = Path(args.backup).expanduser().resolve()
    else:
        root = club_root() / "backups" / slug
        options = sorted((path for path in root.iterdir() if path.is_dir()), reverse=True) if root.exists() else []
        if not options:
            raise ClubError(f"No backup found for {slug}")
        backup = options[0]
    validate_pet_dir(backup)
    target = pet_root() / slug
    displaced = backup_existing(target)
    staging = Path(tempfile.mkdtemp(prefix=f".restore-{slug}-", dir=pet_root()))
    shutil.rmtree(staging)
    shutil.copytree(backup, staging)
    os.replace(staging, target)
    cleared = clear_install_record(slug)
    print(json.dumps({"restored": str(target), "from": str(backup), "previousBackup": str(displaced) if displaced else None, "versionRecordCleared": cleared}, ensure_ascii=False, indent=2))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Manage Codex Pet Club pets")
    root.add_argument("--api", help="registry base URL override")
    sub = root.add_subparsers(dest="command", required=True)

    configure = sub.add_parser("configure")
    configure.add_argument("--api", dest="configure_api", required=True)
    configure.set_defaults(func=command_configure)

    listing = sub.add_parser("list")
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(func=command_list)

    info = sub.add_parser("info")
    info.add_argument("pet_id", metavar="ID")
    info.set_defaults(func=command_info)

    install = sub.add_parser("install")
    install.add_argument("pet_id", metavar="ID")
    install.set_defaults(func=command_install)

    validate = sub.add_parser("validate")
    validate.add_argument("local")
    validate.set_defaults(func=command_validate)

    pack = sub.add_parser("pack")
    pack.add_argument("local")
    pack.add_argument("--output", required=True)
    pack.set_defaults(func=command_pack)

    publish = sub.add_parser("publish")
    publish.add_argument("local")
    publish.set_defaults(func=command_publish)

    status = sub.add_parser("status")
    status.add_argument("submission_id", metavar="SUBMISSION_ID")
    status.set_defaults(func=command_status)

    backups = sub.add_parser("backups")
    backups.set_defaults(func=command_backups)

    installed = sub.add_parser("installed")
    installed.set_defaults(func=command_installed)

    restore = sub.add_parser("restore")
    restore.add_argument("slug")
    restore.add_argument("--backup")
    restore.set_defaults(func=command_restore)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        args.func(args)
        return 0
    except ClubError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
