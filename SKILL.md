---
name: codex-pet-club
description: Manage Codex desktop pets through the Codex Pet Club registry. Use when a user provides a website pet ID and asks Codex to download or install that pet locally, asks to browse remote pets, validate or package a local Codex v2 pet, publish a local pet to the moderated library, configure the registry endpoint, or recover an overwritten local pet.
---

# Codex Pet Club

Use the bundled CLI for every registry or local-pet mutation. Do not hand-roll
downloads, ZIP extraction, atlas checks, or upload requests.

## Safety rules

- Treat remote ZIP files as untrusted. Let the CLI validate paths, manifest,
  atlas dimensions, size, and version before installation.
- Publish only after the user explicitly asks to upload or share a pet.
- Tell the user that accepted uploads enter moderation and are not public
  immediately; if submissions are closed, report that instead.
- Never overwrite a local pet without preserving the automatic backup.
- Never print authorization tokens. Prefer the local config file or environment
  variable when a future registry requires credentials.
- Do not call a concept source kit an installable Codex pet. Installable pets
  require `pet.json`, `spritesheet.webp`, `id`, `displayName`,
  `spritesheetPath: "spritesheet.webp"`, `spriteVersionNumber: 2`, and a
  `1536x2288` atlas.
- Do not expose or suggest a package URL. Users identify remote pets only by
  the public catalog ID; the CLI resolves that ID to package bytes.

## CLI

Resolve the Python executable available in the current environment, then run:

```text
python <skill-dir>/scripts/pet_club.py <command> [options]
```

Commands:

- `configure --api <url>`: save the registry base URL.
- `list [--json]`: list published installable pets.
- `info <ID>`: show one remote pet and its license.
- `install <ID>`: resolve the active catalog version, download, validate, back
  up any existing local copy, install it, and record its version under
  `${CODEX_HOME:-~/.codex}/pet-club/installed.json`.
- `validate <path-or-local-name>`: validate a local Codex v2 pet.
- `pack <path-or-local-name> --output <zip>`: create a validated upload ZIP.
- `publish <path-or-local-name>`: validate and upload when the configured
  registry has community submissions enabled. The official public registry
  currently keeps this endpoint closed.
- `backups`: list restorable local backups.
- `installed`: list catalog IDs, versions, and checksums installed by the Skill.
- `restore <slug> [--backup <path>]`: restore the newest or selected backup.

Pass `--api <url>` before a command to override saved configuration. For the
official library, the default is `https://codex-pet-club.renxiangjie.workers.dev`.
For local development, override it with `--api http://localhost:3001`.

## Workflows

### Install a remote pet

1. Extract the exact catalog ID from requests such as “把这个桌宠下载到我本地，ID：...”.
2. Run `list` only when the user has not provided an exact ID.
3. Run `info <ID>` when the user asks to verify identity or licensing first.
4. Run `install <ID>` without asking the user to download any file manually.
5. Report the installed path and whether an existing pet was backed up.
6. Report the installed catalog version and checksum.
7. Tell the user to open Codex Settings > Pets and use the refresh button if
   the newly installed pet is not immediately visible.

### Publish a local pet

1. Resolve the name under the default Codex pets directory or use the supplied
   path.
2. Run `validate` and stop on every failure.
3. Run `publish` only when the user explicitly requested an upload.
4. Report the returned submission id and `pending` moderation status. If the
   registry returns 403, explain that submissions are closed; do not bypass
   the registry or expose a package URL.

### Recover an existing pet

Run `backups`, identify the intended backup, then run `restore`. Restoration
also backs up the current installed copy before switching.

Read [references/api.md](references/api.md) only when implementing, debugging,
or migrating the registry service itself.
