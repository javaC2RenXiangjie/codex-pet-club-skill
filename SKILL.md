---
name: codex-pet-club
description: Manage Codex desktop pets through the Codex Pet Club registry. Use when a user asks to browse remote pets, install or update a pet automatically, validate or package a local Codex v2 pet, publish a local pet to the moderated remote library, configure the registry endpoint, or recover an overwritten local pet.
---

# Codex Pet Club

Use the bundled CLI for every registry or local-pet mutation. Do not hand-roll
downloads, ZIP extraction, atlas checks, or upload requests.

## Safety rules

- Treat remote ZIP files as untrusted. Let the CLI validate paths, manifest,
  atlas dimensions, size, and version before installation.
- Publish only after the user explicitly asks to upload or share a pet.
- Tell the user that uploads enter moderation and are not public immediately.
- Never overwrite a local pet without preserving the automatic backup.
- Never print authorization tokens. Prefer the local config file or environment
  variable when a future registry requires credentials.
- Do not call a concept source kit an installable Codex pet. Installable pets
  require `pet.json`, `spritesheet.webp`, `spriteVersionNumber: 2`, and a
  `1536x2288` atlas.

## CLI

Resolve the Python executable available in the current environment, then run:

```text
python <skill-dir>/scripts/pet_club.py <command> [options]
```

Commands:

- `configure --api <url>`: save the registry base URL.
- `list [--json]`: list published installable pets.
- `info <slug>`: show one remote pet and its license.
- `install <slug>`: download, validate, back up any existing copy, and install.
- `validate <path-or-local-name>`: validate a local Codex v2 pet.
- `pack <path-or-local-name> --output <zip>`: create a validated upload ZIP.
- `publish <path-or-local-name>`: validate and upload to the moderation queue.
- `backups`: list restorable local backups.
- `restore <slug> [--backup <path>]`: restore the newest or selected backup.

Pass `--api <url>` before a command to override saved configuration. For the
local prototype, use `--api http://localhost:3001`.

## Workflows

### Install a remote pet

1. Run `list` when the user has not provided an exact slug.
2. Confirm the selected pet name and license in the normal response.
3. Run `install <slug>`.
4. Report the installed path and whether an existing pet was backed up.

### Publish a local pet

1. Resolve the name under the default Codex pets directory or use the supplied
   path.
2. Run `validate` and stop on every failure.
3. Run `publish` only when the user explicitly requested an upload.
4. Report the returned submission id and `pending` moderation status.

### Recover an existing pet

Run `backups`, identify the intended backup, then run `restore`. Restoration
also backs up the current installed copy before switching.

Read [references/api.md](references/api.md) only when implementing, debugging,
or migrating the registry service itself.
