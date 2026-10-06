# Demo scenario

The Workbench uses customer `C001` and a synthetic call:

1. Start the call.
2. Add a positive service segment and a negative monthly-fee segment.
3. Request assistance. The fixed propensity is high, but the authoritative complaint is open, so the visible outcome is `SUPPRESS`.
4. Resolve the complaint through the authorized business operation.
5. Request assistance again. `SAVINGS_PLUS` becomes eligible and the recommendation is published with structured facts and guidance evidence.
6. End the call and run post-call enrichment.
7. Run the same post-call operation again to observe idempotency.

The API and trace drawer expose state versions, transcript versions, UI sequence numbers, dependency snapshots, lifecycle, and evidence refs.
