#!/usr/bin/env python3
"""Build the deterministic runtime ZIP used by the automatic updater."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import zipfile


RELEASE_FILES = (
    "SKILL.md",
    "LICENSE",
    "SECURITY.md",
    "agents/openai.yaml",
    "references/api.md",
    "scripts/pet_club.py",
    "scripts/skill_update.py",
)
VERSION_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
FIXED_TIMESTAMP = (2020, 1, 1, 0, 0, 0)


def build_release(repo: Path, output: Path, version: str) -> dict:
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError("version must use x.y.z")
    expected_name = f"codex-pet-club-skill-v{version}.zip"
    if output.name != expected_name:
        raise ValueError(f"output file must be named {expected_name}")
    version_source = (repo / "scripts" / "pet_club.py").read_text(encoding="utf-8")
    if f'SKILL_VERSION = "{version}"' not in version_source:
        raise ValueError("release version does not match scripts/pet_club.py")
    for relative in RELEASE_FILES:
        if not (repo / relative).is_file():
            raise ValueError(f"release input is missing {relative}")

    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{output.name}-", dir=output.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for relative in RELEASE_FILES:
                source = repo / relative
                info = zipfile.ZipInfo(relative, date_time=FIXED_TIMESTAMP)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                mode = 0o755 if relative.startswith("scripts/") else 0o644
                info.external_attr = mode << 16
                archive.writestr(info, source.read_bytes())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)

    raw = output.read_bytes()
    return {
        "version": version,
        "output": str(output),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "sizeBytes": len(raw),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    result = build_release(repo, Path(args.output).expanduser().resolve(), args.version)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
