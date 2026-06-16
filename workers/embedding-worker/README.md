# Embedding Worker

Consumes normalized observed evidence events, calls the local Qwen inference API, and upserts named vectors into Qdrant.

Default consumed topics:

- `evidence.posts.observed.v1`
- `evidence.accounts.observed.v1`
- `evidence.media.observed.v1`
- `evidence.search.results.v1`
- `evidence.web.documents.observed.v1`
- `evidence.user.inputs.observed.v1`

The worker writes vector data to Qdrant and emits vector metadata, not full vectors, to `osint.semantic.embedded.v1`.
