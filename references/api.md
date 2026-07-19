# Codex Pet Club registry API

## Contract

All successful responses are JSON except package bytes.

### `GET /api/pets`

Return only published, installable Codex v2 pets:

```json
{"pets":[{"id":"9d1ef2a4-55df-4d99-a722-18d1db7cb83a","petKey":"pixel-corgi","displayName":"像素柯基","description":"...","author":"...","license":"MIT","version":"1.2.0","sha256":"...","sizeBytes":12345,"updatedAt":"..."}]}
```

`id` is the public catalog ID copied from the website. `petKey` is the
`pet.json` id and becomes the local folder name under `~/.codex/pets`.

### `GET /api/pets/{id}`

Return the same metadata shape as one `pet` object. Return 404 for missing or
unpublished entries.

### `GET /api/pets/{id}/package`

Return package bytes with a private no-store cache policy, an `ETag` based on
SHA-256, the checksum in `x-pet-sha256`, and the manifest id in `x-pet-key`.
Return the active catalog version in `x-pet-version`.
The website never links this endpoint; the Skill resolves catalog IDs and
consumes the bytes. Require `x-codex-pet-client: skill-v1` to reject ordinary
browser navigation. This header is an interface guard, not a secret or DRM
boundary, because the Skill is open source.

Published entries retain immutable releases. The public catalog exposes only
the entry selected by `activeVersion`; unpublished entries return 404 without
deleting their historical package objects.

### `POST /api/pets`

The official public registry accepts moderated Skill submissions using the
contract below. No account is required in the first release; server-side ZIP
validation, duplicate protection, a bounded pending queue, and manual review
prevent uploads from becoming public directly.

Accept `multipart/form-data` fields:

- `package`: ZIP, at most 32 MiB.
- `metadata`: JSON with optional `description`, `author`, and `license`.

The ZIP must contain one top-level pet folder or a flat root with `pet.json`
and `spritesheet.webp`. The manifest must include `id`, `displayName`,
`spritesheetPath: "spritesheet.webp"`, and `spriteVersionNumber: 2`; the WebP
atlas must report `1536x2288`. Validate ZIP traversal, duplicates, expanded
size, manifest fields, and atlas dimensions server-side even though the Skill
already validates locally.

Return HTTP 202:

```json
{"submission":{"id":"...","petKey":"...","status":"pending","sha256":"...","statusPath":"/api/submissions/..."}}
```

Uploads are never published directly. A moderator changes `pending` to
`published` after visual, licensing, and safety review. That submission id
becomes the public catalog ID when published.

### `GET /api/submissions/{id}`

Return the current moderation status for an unguessable submission ID:

```json
{"submission":{"id":"...","petKey":"...","displayName":"...","status":"pending","sha256":"...","createdAt":"...","updatedAt":"...","reviewedAt":null,"reviewNote":""}}
```

Possible states are `pending`, `published`, and `rejected`. A published
submission is immediately available through the normal public pet endpoints
using the same ID.

## Storage

- `registry/catalog.json`: version history and active versions for official
  releases shipped with the Worker.
- D1 `DB`: pending, published, and rejected community submission metadata.
- R2 `PET_FILES`: immutable published ZIP bytes under
  `packages/{catalog-id}/{version}/{sha256}.zip`; pending bytes stay isolated
  until approval.
- Public listing endpoints merge official releases with D1 rows whose status
  is `published`.
