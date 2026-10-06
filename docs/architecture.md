# Architecture

The platform is a modular monolith with three execution paths sharing domain contracts:

1. **Live assistance** accepts transcript revisions, recomputes derived conversation state from a canonical whole-transcript snapshot, evaluates commercial policy, and publishes complete assistance-view snapshots.
2. **Post-call enrichment** binds work to an immutable transcript snapshot and persists one idempotent result selected by `(transcript_version, enrichment_version)`.
3. **Supervisor history** enumerates authorized interaction records before summarizing them, so a similarity result cannot be mistaken for complete history.

## Correctness boundaries

- A per-call coordinator serializes state mutation and publication commit. External model, retrieval, and network calls occur outside that lock.
- Canonical transcript version is whole-input state. A derived result for an older snapshot is discarded even if the individual triggering segment is still current.
- `state_version` invalidates in-flight decisions. Dependency expiry can invalidate a decision even without a new transcript event.
- Authorization is injected by trusted runtime code and revalidated for late effects. Model output never supplies identity, permissions, or customer scope.
- Business outcome (`RECOMMEND`, `SUPPRESS`, `UNAVAILABLE`, `NO_ELIGIBLE_OPTION`) is distinct from delivery lifecycle.
- The browser receives a complete assistance snapshot. It adopts only the highest `ui_seq`, making inverse-order delivery safe.
- Structured product facts and scores are rendered from controlled fields. Free text is validated for schema, citations, protected values, and policy boundaries; arbitrary semantic truth is not claimed.
- Tombstones and final writes share the SQLite transaction boundary, preventing deletion/retry resurrection.

## Production mapping

The local adapters can later map to a streaming conversation connector, a managed hot-state store, a governed search index, enterprise identity, and an event transport. The local contracts are intentionally independent of those deployment choices.
