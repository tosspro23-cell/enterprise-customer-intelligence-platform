# Demo scenarios

The Workbench is designed as a business-facing agent desktop. The left rail contains three synthetic call Scripts; the transcript is advanced event by event, while the right side shows the current customer state and the assistance available to the agent:

- **费用投诉** (`C001`) — positive service feedback becomes a fee complaint, commercial assistance is suppressed, and a later authorized resolution allows a grounded recommendation.
- **储蓄咨询** (`C001`) — a resolved service context moves into a product-information question, showing how approved facts and guidance become an optional next step.
- **账单争议** (`C002`) — service and billing concerns are separated, the billing issue is handled first, and only then can a follow-up suggestion be evaluated.

The primary walkthrough is the **费用投诉** Script:

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

The **客服工作台** shows the business state in action language: what the customer needs now, what the agent should do next, and whether an assistant suggestion is available. The transcript remains the primary timeline; metrics and assistance change only after the corresponding event has been processed. **Supervisor 历史分析** enumerates the authorized interaction records rather than selecting a small similarity sample, then exposes service outcome, decision history, post-call summary, evidence coverage, and expandable traces for the selected call.

The scenario catalog is served by `GET /api/demo/scenarios`. Supervisor history is served by `GET /api/supervisor/interactions`, which combines persisted interaction records with the assistance and trace evidence needed for review.

This keeps the implementation contract's evidence requirement while preserving the architecture boundary: a standalone Workbench is a reference/demo surface, while production suggestions would normally be embedded in the existing agent desktop/widget.
