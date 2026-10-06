# Demo scenarios

The Workbench is designed as a business-facing agent desktop. The left rail contains three synthetic multi-turn call scripts; each dialogue turn arrives as its own transcript event and appears in a chat-style timeline with the customer on the left and the agent on the right. The right side shows the current customer state and the assistance available to the agent. “Run full conversation” pauses for about 2.4 seconds after each spoken turn and a shorter pause after system events, so the state change remains visible in the browser:

- **费用投诉** (`C001`) — 13 alternating customer/agent turns move from an unrecognized charge to a confirmed resolution, with commercial assistance suppressed until the issue is resolved.
- **储蓄咨询** (`C001`) — 7 alternating turns clarify the customer’s savings goal, product questions, and approved facts before the optional recommendation is evaluated.
- **账单争议** (`C002`) — 13 alternating turns separate the billing concern from the later savings question, so the billing issue is handled before a follow-up suggestion is evaluated.

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

The **Agent Workbench** shows the business state in action language: what the customer needs now, what the agent should do next, and whether an assistant suggestion is available. The transcript remains the primary timeline; metrics, assistance, and the compact **Workflow event** card change only after the corresponding event has been processed. Platform and business-workflow steps therefore expose their result explicitly, such as complaint authority becoming `RESOLVED`, a recommendation becoming `SUPPRESS` or `RECOMMEND`, and delivery moving through `SERVER_PUBLISHED` and `UI_ACKNOWLEDGED`. **Supervisor analytics** is a separate historical-analysis console: it removes the script navigation and live-call controls, then exposes the full authorized interaction history, aggregate service analysis, outcome distribution, post-call summary, evidence coverage, and expandable traces for the selected call.

The scenario catalog is served by `GET /api/demo/scenarios`. Supervisor history is served by `GET /api/supervisor/interactions`, which combines persisted interaction records with the assistance and trace evidence needed for review.

This keeps the implementation contract's evidence requirement while preserving the architecture boundary: a standalone Workbench is a reference/demo surface, while production suggestions would normally be embedded in the existing agent desktop/widget.
