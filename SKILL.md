---
name: codex-pet-club
description: Manage Codex desktop pets through the Codex Pet Club registry. Use when a user provides a website pet ID and asks Codex to download or install that pet locally, bind or remove a creator Skill Key, inspect the bound account, browse remote pets, validate or package a local Codex v2 pet, publish an account-owned pet to the moderated library, configure the registry endpoint, or recover an overwritten local pet.
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
- Never print, log, or repeat a Skill Key. Persist it only through the CLI,
  prefer `--key-stdin` when possible, and report only the masked preview.
- Let the CLI perform its automatic version check before every command. Never
  bypass its official-release URL, size, SHA-256, or archive safety checks.
- When the CLI returns `"restartRequired": true`, stop. Tell the user the Skill
  was upgraded and ask them to repeat the request in their next Codex turn so
  the new `SKILL.md` is loaded. Do not run the original command in that turn.
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

- `version`: show the installed Skill version and automatic-update capability.
- `configure [--api <url>] [--key <key> | --key-stdin | --clear-key]`: save
  the registry URL, validate and bind a creator Key, or remove the local Key.
- `account`: validate the saved Key and show the bound creator identity using a
  masked email and Key preview.
- `list [--json]`: list published installable pets.
- `info <ID>`: show one remote pet and its license.
- `install <ID>`: resolve the active catalog version, download, validate, back
  up any existing local copy, install it, and record its version under
  `${CODEX_HOME:-~/.codex}/pet-club/installed.json`.
- `validate <path-or-local-name>`: validate a local Codex v2 pet.
- `pack <path-or-local-name> --output <zip>`: create a validated upload ZIP.
- `publish <path-or-local-name>`: require the bound Key, validate and upload to
  the protected moderation queue, and bind the submission to that account.
- `status <SUBMISSION_ID>`: query whether an upload is pending, published,
  unpublished, or rejected, including the moderator note when present.
- `backups`: list restorable local backups.
- `installed`: list catalog IDs, versions, and checksums installed by the Skill.
- `restore <slug> [--backup <path>]`: restore the newest or selected backup.

Pass `--api <url>` before a command to override saved configuration. For the
official library, the default is `https://codex-pet-club.renxiangjie.workers.dev`.
For local development, override it with `--api http://localhost:3001`.
Use `CODEX_PET_CLUB_KEY` only as a temporary override; the normal flow stores
the Key under `${CODEX_HOME:-~/.codex}/pet-club/config.json`.

Every CLI invocation first checks the official registry's tiny version
manifest. If a newer release exists, the CLI downloads only the matching
official GitHub Release, verifies its size and SHA-256, validates every archive
path, installs it transactionally, and removes the transient old directory.
Configuration, creator Key, installed-pet records, and pet backups remain under
`${CODEX_HOME:-~/.codex}/pet-club` outside the Skill folder. Network or version
service unavailability does not block the current installed version.

## Workflows

### Bind a creator account

1. Accept only a Key the user explicitly provides from the website account
   page. Never invent, request by email, or recover a Key.
2. Run `configure --key-stdin` when the execution environment can pipe the Key
   without echoing it; otherwise run `configure --key <KEY>`.
3. Let the CLI validate the Key against `/api/me` before saving it.
4. Report the masked Key preview, display name, and masked email only.
5. Run `account` when the user asks which account is currently bound.
6. Run `configure --clear-key` when the user asks to unbind this computer. This
   does not revoke the Key on other computers; revocation happens on the site.

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
3. Confirm a creator Key is bound with `account`. If no Key is configured, tell
   the user to create one on `/account` and bind it before publishing.
4. Run `publish` only when the user explicitly requested an upload. The CLI
   attaches the Key without including it in output.
5. Report the returned submission id, status URL, and `pending` moderation
   status. Never claim that a pending upload is publicly available.
6. When the user asks for progress, run `status <SUBMISSION_ID>` and report the
   current state. A `published` submission can be installed with the same ID.
7. If publishing returns a rate-limit error, report the retry interval and stop;
   do not retry automatically. If status is `unpublished`, explain that the pet
   was removed from the public catalog and cannot be newly installed.

### Recover an existing pet

Run `backups`, identify the intended backup, then run `restore`. Restoration
also backs up the current installed copy before switching.

Read [references/api.md](references/api.md) only when implementing, debugging,
or migrating the registry service itself.
