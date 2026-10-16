# Phase 2 increment 01: bounded model boundary

## Decision

The first AWS Phase 2 increment strengthens the existing explanation adapter
boundary before adding Bedrock, PostgreSQL, or a multi-task runtime. The
deterministic adapter remains the default and continues to be the reference
for contract tests.

This ordering follows the cross-cloud comparison: the Azure implementation
already demonstrates a real-model adapter, while the AWS deployment currently
proves only the deterministic path. The next useful AWS step is therefore to
make the provider boundary safe and observable, not to copy the Azure service
inventory.

## Scope

- Move the synchronous Azure OpenAI HTTP call to a worker thread so a slow
  provider response cannot block the FastAPI event loop.
- Reject explanation prose that introduces an amount other than the approved
  fee, a currency other than the approved currency, or unsupported financial
  promises such as guaranteed returns.
- Keep business facts, eligibility, evidence references, and publication state
  deterministic and authoritative.
- Add local tests for accepted claims, rejected claims, and the non-blocking
  adapter boundary.

## Explicit non-goals

- No Bedrock deployment or real-model enablement on the Phase One endpoint.
- No change to the default deterministic model path.
- No PostgreSQL, cache, event bus, Transcribe, Polly, or Fargate resources.
- No claim that prose validation proves arbitrary natural-language truth.

## Acceptance evidence

The increment is complete when:

1. the deterministic suite passes;
2. the validator rejects altered fees, currencies, and unsupported financial
   claims while accepting the approved facts; and
3. the provider adapter test proves that synchronous HTTP is delegated through
   `asyncio.to_thread`.

The next increment should define the persistence port and PostgreSQL migration
contract. It must precede Fargate or any multi-instance deployment.
