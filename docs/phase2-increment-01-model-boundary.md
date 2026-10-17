# Phase 2 increment 01: bounded model boundary and Bedrock canary

## Decision

The first AWS Phase 2 increment strengthens the explanation adapter boundary
while adding a bounded Bedrock adapter. The deterministic adapter remains the
local/default path and continues to be the reference for contract tests; the
real provider is enabled only for an explicit, reversible AWS canary.

The useful AWS step is therefore a small Bedrock Runtime adapter behind the
existing port, not a broad service inventory or a replacement of the existing
business-policy boundary.

## Scope

- Add a Bedrock Runtime `Converse` adapter selected only by
  `LLM_PROVIDER=bedrock` and `BEDROCK_MODEL_ID`.
- Move the synchronous Bedrock SDK call to a worker thread so a slow provider
  response cannot block the FastAPI event loop.
- Reject explanation prose that introduces an amount other than the approved
  fee, a currency other than the approved currency, or unsupported financial
  promises such as guaranteed returns.
- Compare at least three accessible Bedrock profiles with bounded concurrency,
  latency measurements, and the existing explanation validator.
- Enable the selected profile on the existing synthetic EC2 demo only after
  CI, image-digest, health, scenario, and trace checks pass.
- Keep business facts, eligibility, evidence references, and publication state
  deterministic and authoritative.
- Add local tests for accepted claims, rejected claims, and the non-blocking
  adapter boundary.

## Explicit non-goals

- No production-data enablement, public identity boundary, or production SLA.
- No change to the local/default deterministic model path.
- No PostgreSQL, cache, event bus, Transcribe, Polly, or Fargate resources.
- No claim that prose validation proves arbitrary natural-language truth.

## Acceptance evidence

The increment is complete when:

1. the deterministic suite passes;
2. the validator rejects altered fees, currencies, and unsupported financial
   claims while accepting the approved facts; and
3. the Bedrock adapter tests prove that the synchronous SDK call is delegated
   through `asyncio.to_thread` and that a Converse response is mapped into the
   bounded explanation result;
4. the three-model benchmark records success, validation, rubric, and latency
   results, with a hard gate for the selected default; and
5. the AWS canary proves the deployed health configuration and records a
   successful real-model decision trace with synthetic data.

The next increment should define the persistence port and PostgreSQL migration
contract. It must precede Fargate or any multi-instance deployment.
