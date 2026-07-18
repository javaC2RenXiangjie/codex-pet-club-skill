# Codex Pet Club registry API

## Contract

All successful responses are JSON except package downloads.

### `GET /api/pets`

Return published, installable Codex v2 pets:

```json
{"pets":[{"slug":"pixel-corgi","name":"像素柯基","description":"...","author":"...","license":"MIT","sha256":"...","sizeBytes":12345,"updatedAt":"..."}]}
```

### `GET /api/pets/{slug}`

Return the same metadata shape as one `pet` object. Return 404 for missing or
unpublished entries.

### `GET /api/pets/{slug}/package`

Return an `application/zip` package with `Content-Disposition: attachment`, an
`ETag` based on SHA-256, and the package checksum in `x-pet-sha256`.

### `POST /api/pets`

Accept `multipart/form-data` fields:

- `package`: ZIP, at most 32 MiB.
- `metadata`: JSON with optional `description`, `author`, and `license`.

The ZIP must contain one top-level pet folder or flat root with `pet.json` and
`spritesheet.webp`. The manifest must use `spriteVersionNumber: 2`; the WebP
atlas must report `1536x2288`. Validate ZIP traversal, duplicates, compression
size, manifest fields, and atlas dimensions server-side even though the Skill
already validates locally.

Return HTTP 202:

```json
{"submission":{"id":"...","slug":"...","status":"pending","sha256":"..."}}
```

Uploads are never published directly. A moderator changes `pending` to
`published` after visual, licensing, and safety review.

## Storage

- D1 `DB`: searchable metadata and moderation status.
- R2 `PET_FILES`: ZIP bytes under `pending/` or `published/` keys.
- Public listing endpoints return only `published` rows.
