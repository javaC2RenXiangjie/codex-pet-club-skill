# Codex Pet Club registry API

## Contract

All successful responses are JSON except package bytes.

### `GET /api/pets`

Return only published, installable Codex v2 pets:

```json
{"pets":[{"id":"9d1ef2a4-55df-4d99-a722-18d1db7cb83a","petKey":"pixel-corgi","displayName":"像素柯基","description":"...","author":"...","license":"MIT","sha256":"...","sizeBytes":12345,"updatedAt":"..."}]}
```

`id` is the public catalog ID copied from the website. `petKey` is the
`pet.json` id and becomes the local folder name under `~/.codex/pets`.

### `GET /api/pets/{id}`

Return the same metadata shape as one `pet` object. Return 404 for missing or
unpublished entries.

### `GET /api/pets/{id}/package`

Return package bytes with a private no-store cache policy, an `ETag` based on
SHA-256, the checksum in `x-pet-sha256`, and the manifest id in `x-pet-key`.
The website never links this endpoint; the Skill resolves catalog IDs and
consumes the bytes. Require `x-codex-pet-client: skill-v1` to reject ordinary
browser navigation. This header is an interface guard, not a secret or DRM
boundary, because the Skill is open source.

### `POST /api/pets`

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
{"submission":{"id":"...","petKey":"...","status":"pending","sha256":"..."}}
```

Uploads are never published directly. A moderator changes `pending` to
`published` after visual, licensing, and safety review. That submission id
becomes the public catalog ID when published.

## Storage

- D1 `DB`: searchable metadata, unique catalog ID, and moderation status.
- R2 `PET_FILES`: ZIP bytes under pending or published object keys.
- Public listing endpoints return only `published` rows.
