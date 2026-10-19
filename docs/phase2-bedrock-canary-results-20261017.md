# Phase Two Bedrock canary results

Status: preliminary model-selection evidence for the AWS reference deployment.
The 2026-10-19 rerun supersedes the original table below.

## Test boundary

- Initial run date: 2026-10-17
- Latest rerun date: 2026-10-19
- Region: `us-east-1`
- Inputs: synthetic customer-interaction requests only
- Candidates: three accessible Bedrock inference profiles
- Cases: complaint suppression, approved recommendation, provider unavailable
- Repetitions: four per case and model, 12 requests per model
- Concurrency: four in-flight requests
- Total: 36 real Bedrock requests
- Adapter path: `BedrockExplanationAdapter` through Bedrock Runtime `Converse`
- Validation: the existing deterministic explanation validator plus a strict
  case-specific business-language rubric. A response passes the rubric only
  when it contains every configured required term for its case.

This is a bounded canary comparison. It is not a production SLA, a capacity
test, or evidence that the application is ready for real customer data.

## Results

| Candidate | Requests | Success | Validation pass | Rubric pass | Mean latency | P50 | P95 | Composite |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Amazon Nova Micro (`us.amazon.nova-micro-v1:0`) | 12 | 100% | 100% | 91.67% | 675 ms | 637 ms | 878 ms | 0.9750 |
| Anthropic Claude Haiku 4.5 (`us.anthropic.claude-haiku-4-5-20251001-v1:0`) | 12 | 100% | 100% | 66.67% | 1,248 ms | 1,296 ms | 1,527 ms | 0.8575 |
| Meta Llama 3.3 70B (`us.meta.llama3-3-70b-instruct-v1:0`) | 12 | 100% | 91.67% | 66.67% | 874 ms | 853 ms | 1,291 ms | 0.8180 |

The composite score is only used for this first comparison:

```text
validation 60% + deterministic rubric 30% + relative P95 latency 10%
```

The hard eligibility gate is 100% request success and 100% explanation
validation. Under that gate, Nova Micro is the preliminary default because it
has the highest composite score and the lowest P95 latency among the fully
validated candidates. The stricter rubric passed 11 of 12 Nova requests; this
is useful selection evidence, not a claim of unrestricted model correctness.

## Decision

Set `us.amazon.nova-micro-v1:0` as the preliminary default model **inside the
Bedrock provider**. Keep the application-wide default provider as `fake` until
the live canary is explicitly enabled with `LLM_PROVIDER=bedrock`. This
preserves the deterministic local/reference behavior and makes the
production-like model path an observable, reversible deployment choice. The
deterministic validator remains authoritative for publication; the rubric is
only a bounded model-selection signal.

Claude Haiku 4.5 remains a quality comparison candidate. It passed the
explanation validator but was slower and had a lower strict-rubric rate in this
run. Llama 3.3 70B is not eligible as the default because one request failed
the existing explanation validator; its lower latency does not compensate for
violating the explanation contract.

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

The live canary must remain synthetic-only.

## Live canary evidence

The live canary was subsequently enabled on the existing Phase One host with
the CI-validated image tag `81e3a8e`.

- CloudFormation status: `UPDATE_COMPLETE`
- EC2 instance: unchanged from Phase One
- Endpoint: unchanged Elastic-IP-backed demo URL
- Health: `llm_provider=bedrock`, `llm_model_id=us.amazon.nova-micro-v1:0`
- Scenarios: all three remained available
- Image digest: `sha256:bfef76a5e6f43f7a1d76c05422fe5a18920370812bea76bcd92fa31040b4eec8`
- Synthetic end-to-end call: transcript → complaint resolution → commercial
  decision completed with `PUBLISH_COMMITTED`
- Trace stages included successful `llm_explanation`,
  `explanation_validation`, and `commercial_publication`; the final
  publication trace recorded `model_version=us.amazon.nova-micro-v1:0`

This proves the real-model adapter is wired through the deployed application
decision path. It does not change the boundary that the application is still a
single-host synthetic demo and that the local/default provider remains
deterministic unless the canary environment explicitly enables Bedrock.
