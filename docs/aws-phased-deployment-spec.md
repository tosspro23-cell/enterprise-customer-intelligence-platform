# AWS Phased Deployment Specification

Status: Proposed for independent architecture review

This specification separates the first AWS cloud test from the later
production-oriented service expansion. The phases are deliberately gated: the
second phase must not be implemented by adding cloud services before the
application contracts, evidence model, security boundary, and cost controls
are ready.

## 1. Objective

Provide a credible cloud path for the customer-intelligence reference
platform while preserving the current business-facing Workbench and its
evidence boundaries.

The deployment must demonstrate:

- live call-state and transcript behavior;
- deterministic business policy and grounded assistance;
- post-call analysis and supervisor history;
- inspectable deployment, update, teardown, and runtime evidence;
- a clear distinction between synthetic demo behavior, cloud validation, and
  production readiness.

The platform remains synthetic-data-only until identity, transport security,
data persistence, retention, and operational controls are explicitly promoted.

## 2. Existing application boundary

The current application is a single FastAPI process with an explicit per-call
coordinator, SQLite persistence, local synthetic guidance, deterministic
business adapters, and an optional bounded language-model adapter.

The following invariants are deployment-independent and must remain true in
both phases:

1. The model may explain grounded facts but does not define facts,
   eligibility, authority, or customer scope.
2. Live assistance is derived from the canonical transcript/state snapshot;
   stale asynchronous work cannot overwrite newer truth.
3. Authorization is supplied by trusted runtime code and revalidated at
   mutation and publication boundaries.
4. Post-call enrichment is bound to an immutable transcript snapshot and is
   idempotent.
5. Transport delivery, server publication, and browser acknowledgement remain
   separate evidence states.
6. Synthetic fixtures and demo principal behavior are labeled as demo-only.

## 3. Phase 1: cloud test foundation

### 3.1 Goal

Run the current reference slice in `us-east-1` with a stable cloud URL and a
repeatable operational path, without changing the application's distributed
state contract.

### 3.2 In-scope AWS resources

| Concern | Phase 1 implementation | Reason |
| --- | --- | --- |
| Image registry | Amazon ECR repository with scan-on-push and a short lifecycle | Commit-tagged, reproducible demo images |
| Runtime | One Amazon EC2 `t3.micro` instance running Docker on Amazon Linux 2023 | Preserves the one-process contract |
| Network | One-AZ VPC, public subnet, no NAT gateway | Avoids unnecessary always-on networking cost |
| Ingress | Security Group TCP/80 from the explicitly supplied CIDR only | Synthetic private demo; no open internet rule |
| Persistence | 20 GiB encrypted gp3 EBS root volume, host runtime directory mounted into the container | Keeps SQLite across container restarts on the same host |
| Instance access | Systems Manager Session Manager through an instance role | No SSH port and no SSH key lifecycle |
| Image pull | Instance role with ECR read access | No registry secret on the host |
| Logs | One CloudWatch Log Group with short retention and scoped write permissions | Runtime troubleshooting without broad IAM access |
| Release update | Explicit SSM command that pulls a commit-tagged image and replaces the container | User data is bootstrap, not rollout |

The implementation is split into `CustomerIntelligenceRepositoryStack` and
`CustomerIntelligenceDemoStack`. A successful CloudFormation deployment is
not considered application acceptance until the runtime smoke checks pass.

### 3.3 Phase 1 acceptance evidence

The following evidence is required before calling Phase 1 complete:

- local unit, integration, and acceptance tests pass;
- Docker builds from a clean checkout for `linux/amd64`;
- CDK synthesizes both stacks without cloud credentials;
- the deployed container returns a healthy response;
- all three scenario fixtures are available through the deployed API;
- the SQLite file is created under the mounted runtime directory;
- a container restart preserves the SQLite file and the application remains
  healthy;
- the SSM update path replaces the running image and reports remote failure
  rather than only command-submission success;
- CloudWatch receives application logs;
- the endpoint is reachable only from the supplied CIDR;
- teardown behavior and retained ECR artifacts are documented;
- the AWS Billing/Free Tier page is checked after the smoke test.

### 3.4 Phase 1 non-goals

Phase 1 does not include:

- real customer data or real telephony;
- enterprise user authentication or supervisor authorization;
- HTTPS/TLS termination for a public production endpoint;
- horizontal scaling or multi-instance SQLite;
- managed search, managed hot-state, or external event streaming;
- AWS-native speech, language, or model execution;
- unattended deployment from GitHub Actions;
- disaster recovery, multi-AZ failover, or a production SLA.

## 4. Phase 2: reference-cloud parity and production-shaped runtime

### 4.1 Goal

Replace local and single-host boundaries with managed AWS services only after
the corresponding application ports and operational contracts are tested.
Phase 2 is a program of separate PRs, not one large infrastructure change.

### 4.2 Target service mapping

| Capability in the reference cloud implementation | AWS target | Required contract decision |
| --- | --- | --- |
| Managed container environment | ECS on Fargate, with separate UI and headless tasks | Service/task boundary, scaling, health, and rollout semantics |
| Public Workbench ingress | Application Load Balancer + ACM certificate + optional WAF | HTTPS, authentication, client IP policy, and rate limits |
| Internal load-test runner | Internal ECS service/task or scheduled task | No public trigger; explicit operator authorization |
| Hot per-call state | ElastiCache for Valkey/Redis | TTL, key ownership, failure behavior, and concurrency model |
| Partitioned domain-event stream | Kinesis Data Streams when ordering/replay matters; EventBridge when routing/fan-out is the primary need | Ordering, replay, retention, consumers, and delivery guarantees |
| Managed analytical persistence | RDS PostgreSQL or Aurora PostgreSQL | Migrations, transactions, indexes, backup, retention, and tenant scope |
| Curated guidance retrieval | OpenSearch Serverless or Bedrock Knowledge Bases | Corpus ownership, indexing, citations, freshness, and query cost |
| Real-time speech path | Amazon Transcribe Streaming + Amazon Polly | Audio retention, latency budget, voice policy, and failure fallback |
| Sentiment/language enrichment | Amazon Comprehend plus deterministic taxonomy logic | Aspect semantics, model versioning, and evidence labeling |
| Bounded model explanation | Amazon Bedrock adapter or an explicitly governed external model adapter | Model access, region, timeout, fallback, content filtering, and cost limits |
| Runtime secrets | AWS Secrets Manager and task/instance roles | No long-lived application keys in images or source |
| Service identity | IAM roles for workloads; Cognito or external OIDC for users | Agent/supervisor authorization and tenant isolation |
| Observability | CloudWatch metrics/logs, traces through OpenTelemetry/ADOT, dashboards and alarms | Correlation IDs, payload redaction, latency/error SLOs, and audit retention |
| Deployment | GitHub Actions with OIDC to AWS, ECR image digests, approval-gated CDK deploy | Provenance, rollback, and no static GitHub cloud keys |

### 4.3 Recommended Phase 2 order

1. **Persistence adapter:** introduce a storage port and migration tests;
   prove PostgreSQL semantics before changing the runtime.
2. **Identity and secret boundary:** add workload roles, Secrets Manager, and
   a real user authentication/authorization contract.
3. **Managed runtime:** move the stateless HTTP process to ECS/Fargate behind
   an HTTPS ALB; keep the headless worker internal.
4. **Hot state and events:** add Valkey/Redis and select Kinesis or EventBridge
   based on the finalized delivery contract.
5. **AI adapters:** add Bedrock, Transcribe, Polly, and Comprehend behind the
   existing ports; retain deterministic fallbacks and evidence labels.
6. **Retrieval:** add managed search only when the guidance corpus requires
   ranked retrieval, filtering, or independent update cadence.
7. **Operations:** add dashboards, alarms, backups, rollback, load tests,
   budget controls, and a recovery runbook.

Each increment must have a separate acceptance suite that proves the
cross-boundary invariant it introduces. Green infrastructure synthesis alone
is not acceptance.

## 5. Security and cost guardrails

### Phase 1

- Use a non-root AWS identity for CLI/CDK operations.
- Keep the demo CIDR narrow, normally a `/32`.
- Do not put credentials in the image, repository, or GitHub Actions secrets.
- Use synthetic data only.
- Keep the ECR repository retained deliberately, and document its cleanup.
- Review Cost Management after deployment and destroy the demo stack when it
  is not needed.

### Phase 2

- No public database, cache, stream, or search endpoint.
- Prefer private subnets and VPC endpoints; use NAT only where its cost and
  necessity are proven.
- Require HTTPS and real identity before any non-synthetic data.
- Add resource tags, budgets, anomaly alerts, log retention, backup policy,
  and deletion protection where appropriate.
- Define data residency, retention, deletion, and audit requirements before
  enabling audio or transcript ingestion.

## 6. Phase gates

### Gate A: Phase 1 ready for cloud test

- The current AWS PR is reviewed and CI is green.
- A non-root deployment identity is available.
- The selected region and demo CIDR are recorded.
- The operator understands that the endpoint is synthetic-data-only and
  HTTP-only.

### Gate B: Phase 1 accepted

- The complete runtime smoke evidence in Section 3.3 is retained.
- Actual costs and remaining credits are checked.
- The deployed update and teardown paths are exercised at least once.

### Gate C: Phase 2 design freeze

- Persistence, identity, event delivery, and retrieval contracts are reviewed.
- A service-by-service cost estimate and teardown strategy exist.
- The production-shaped threat model and data classification are approved.
- Each Phase 2 increment has an owner, rollback path, and acceptance tests.

## 7. Open decisions for independent review

The architecture review should explicitly challenge these choices:

1. Is EC2 the right Phase 1 runtime, or is App Runner worth its managed HTTPS
   boundary despite the persistence refactor it would require?
2. Should Phase 2 use ECS/Fargate or App Runner for the public Workbench?
3. Does the event contract require Kinesis ordering/replay, or is EventBridge
   routing sufficient?
4. Is ElastiCache/Valkey enough for ephemeral call state, or is durable
   MemoryDB justified?
5. Should structured guidance use OpenSearch Serverless or a Bedrock Knowledge
   Base, and what evidence must be stored for every result?
6. Should the analytical store be RDS PostgreSQL or Aurora PostgreSQL, given
   the account credits and the intended idle schedule?
7. What is the smallest acceptable identity boundary for an agent versus a
   supervisor, and how will tenant scope be enforced end to end?
8. Which services may scale to zero, and how will cold-start behavior affect
   the live-assistance latency budget?
9. What must be redacted from CloudWatch, traces, event streams, and model
   requests before any move beyond synthetic data?
10. Which resources are permanent foundations and which must be provisioned
    only for a bounded test window?

## 8. Deliverables

This specification governs the current AWS foundation PR and the subsequent
implementation PRs. The immediate deliverable is Phase 1 cloud validation. A
Phase 2 implementation must not be started from this document alone; the
open decisions above must be resolved in a reviewed design update first.
