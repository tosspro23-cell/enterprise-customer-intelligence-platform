# Phase Two Bedrock canary results

Status: preliminary model-selection evidence for the AWS reference deployment.

## Test boundary

- Date: 2026-10-17
- Region: `us-east-1`
- Inputs: synthetic customer-interaction requests only
- Candidates: three accessible Bedrock inference profiles
- Cases: complaint suppression, approved recommendation, provider unavailable
- Repetitions: four per case and model, 12 requests per model
- Concurrency: four in-flight requests
- Total: 36 real Bedrock requests
- Adapter path: `BedrockExplanationAdapter` through Bedrock Runtime `Converse`
- Validation: the existing deterministic explanation validator plus a small
  case-specific business-language rubric

This is a bounded canary comparison. It is not a production SLA, a capacity
test, or evidence that the application is ready for real customer data.

## Results

| Candidate | Requests | Success | Validation pass | Rubric pass | Mean latency | P50 | P95 | Composite |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Amazon Nova Micro (`us.amazon.nova-micro-v1:0`) | 12 | 100% | 100% | 100% | 678 ms | 623 ms | 875 ms | 1.0000 |
| Anthropic Claude Haiku 4.5 (`us.anthropic.claude-haiku-4-5-20251001-v1:0`) | 12 | 100% | 100% | 100% | 1,168 ms | 1,228 ms | 1,429 ms | 0.9613 |
| Meta Llama 3.3 70B (`us.meta.llama3-3-70b-instruct-v1:0`) | 12 | 100% | 91.67% | 100% | 829 ms | 827 ms | 1,153 ms | 0.9259 |

The composite score is only used for this first comparison:

```text
validation 60% + deterministic rubric 30% + relative P95 latency 10%
```

The hard eligibility gate is 100% request success and 100% explanation
validation. Under that gate, Nova Micro is the preliminary default because it
was both fully valid and the fastest candidate in this run.

## Decision

Set `us.amazon.nova-micro-v1:0` as the default model **inside the Bedrock
provider**. Keep the application-wide default provider as `fake` until the
live canary is explicitly enabled with `LLM_PROVIDER=bedrock`. This preserves
the deterministic local/reference behavior and makes the production-like
model path an observable, reversible deployment choice.

Claude Haiku 4.5 remains a quality comparison candidate. It passed the same
validation checks but was slower in this run. Llama 3.3 70B is not eligible as
the default: one approved-recommendation response introduced the unsupported
claim “interest rate”, causing the existing validator to reject it. Its lower
latency does not compensate for violating the explanation contract.

## Access and interpretation notes

- The Claude and Llama tests used their active regional inference profiles;
  their bare foundation-model identifiers were not treated as equivalent
  deployment inputs.
- An OpenAI GPT-5.5 candidate was not included in the comparison because this
  account returned an access-denied response for the available profile. That
  is an account-access result, not a quality ranking.
- No cost estimate is inferred from this short run. Billing and token pricing
  should be checked separately before sustained testing.

## Reproduction

From the repository root, with the configured AWS profile:

```bash
AWS_CONFIG_FILE=/Users/ting/.aws/config \
AWS_SHARED_CREDENTIALS_FILE=/Users/ting/.aws/credentials \
.venv/bin/python scripts/bedrock_benchmark.py \
  --profile cccp-deployer \
  --region us-east-1 \
  --repetitions 4 \
  --concurrency 4 \
  --output /tmp/bedrock-canary-results.json
```

The next acceptance step is a live EC2 canary using the same adapter and the
Nova Micro profile, followed by health, scenario, decision-evidence, and
rollback checks. The canary must remain synthetic-only.
