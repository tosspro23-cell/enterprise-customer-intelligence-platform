# Data contracts

The core records are defined in `backend/domain/models.py` and are intentionally plain dataclasses so they remain inspectable in tests and adapters.

Important identities:

- Transcript segment identity: `(call_id, segment_id, revision, payload_hash)`.
- Canonical whole-transcript identity: `(call_id, transcript_version, content_hash)`.
- Post-call idempotency identity: `(call_id, transcript_version, enrichment_version)`.
- Security scope: `(tenant_id, principal_id, customer_id, call_id, permission)`.

Product price, fee, eligibility, and propensity values are structured facts. Explanations may cite them, but the language model is not allowed to reinterpret their semantics or invent model rationale.
