# Decisions

- Use explicit Python orchestration for the live path rather than an open-ended agent loop.
- Keep complaint authority independent from sentiment and conversation-derived complaint signal.
- Treat unknown or expired operational authority as a conservative block for a recommendation.
- Use SQLite/in-memory adapters for the reference slice and keep interfaces ready for production stores.
- Make publication outcome-aware: suppression and unavailable states are visible outcomes, not hidden failures.
- Keep delivery callbacks monotonic; a late transport callback is evidence of an attempt, not permission to regress state.
- Keep deterministic contract evidence, optional real-model evidence, transport delivery, and browser acknowledgement as separate evidence classes.
