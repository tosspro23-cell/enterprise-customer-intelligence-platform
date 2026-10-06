# Demo scenario

The Workbench uses customer `C001` and a synthetic call. It is designed to be read as a customer-service business flow, not as a developer test harness:

1. **建立通话** — bind the customer, call, and trusted agent context.
2. **客户表达服务满意** — ingest a finalized transcript segment and derive a positive service aspect.
3. **客户提出月费问题** — ingest a second segment; the fee aspect becomes negative and a complaint signal becomes active.
4. **实时商业门控** — run the commercial path. The propensity score is high, but an open complaint blocks an additional commercial recommendation, so the visible outcome is `SUPPRESS`.
5. **权威解决投诉** — use the authorized business operation to change complaint authority to `RESOLVED`.
6. **生成有效辅助建议** — run the same commercial path again. Eligibility, product facts, guidance, bounded explanation, and validation all pass, so `SAVINGS_PLUS` is published.
7. **交付确认** — record server publication and browser acknowledgement as separate lifecycle events.
8. **结束通话** — end the live interaction and withdraw active real-time assistance.
9. **Post-call 分析** — bind the final transcript snapshot to a summary, themes, sentiment, and evidence refs.
10. **重试与幂等** — run the same post-call operation again; it returns the existing record without duplicating it.

The guided UI shows the business state beside the underlying evidence: canonical transcript and derived versions, sentiment and themes, complaint authority, propensity, eligibility, policy blocking reasons, guidance provenance, decision lifecycle, and trace stages. This makes the reason for `SUPPRESS` and the later `RECOMMEND` visible without requiring the viewer to read the implementation first.
