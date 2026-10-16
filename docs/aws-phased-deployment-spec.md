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

Run the current reference slice in `us-east-1` with a reachable stable demo
endpoint and a repeatable operational path, without changing the application's
distributed state contract. The endpoint uses a stack-owned Elastic IP and is
stable across normal stop/start and image rollout operations while the demo
stack exists. It is not a production URL or a domain-name strategy.

### 3.2 In-scope AWS resources

| Concern | Phase 1 implementation | Reason |
| --- | --- | --- |
| Image registry | Amazon ECR repository with scan-on-push, immutable tags, and a short lifecycle | Commit-tagged, reproducible demo images |
| Runtime | One Amazon EC2 `t3.micro` instance running Docker on Amazon Linux 2023 | Preserves the one-process contract |
| Network | One-AZ VPC, public subnet, no NAT gateway | Avoids unnecessary always-on networking cost |
| Endpoint | Stack-owned Elastic IP associated with the demo instance | Keeps the test and demo URL stable during normal operations |
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
- a minimal call can be started, receive a transcript segment, end, and run
  post-call processing;
- the completed history record remains readable after a container restart with
  the same mounted runtime directory;
- the SQLite file is created under the mounted runtime directory;
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
Phase 2 is a candidate roadmap made of separate PRs, not an implementation
checklist. A service is added only when its requirement, acceptance evidence,
cost boundary, and rollback path are explicit.

### 4.2 Authority and state prerequisites

Before selecting a cache, event service, or runtime topology, freeze the
authority of each state class:

| State class | Authoritative source in the target design | Boundary that must be proven |
| --- | --- | --- |
| Completed interactions, post-call records, and decision evidence | PostgreSQL-compatible durable store; RDS PostgreSQL is the Phase 2 baseline | Transactions, migrations, idempotency, deletion, backup, restore, and tenant scope |
| Live call state and coordination | An explicitly versioned state/coordination contract; it cannot remain an unexamined process-local map when tasks can overlap | Owner/lease or equivalent authority, stale-result rejection, takeover, and recovery rules |
| Guidance corpus and versions | Versioned source corpus; indexes are derived representations | Ingestion, version switching, deletion propagation, permission filtering, and citations |
| Model outputs and business decisions | Deterministic business state plus immutable evidence references | Model output cannot create authority, eligibility, customer scope, or publication permission |
| UI delivery state | The existing monotonic UI and delivery evidence model | Client ordering and recovery cannot become the source of business truth |

Shared persistence alone does not make the current in-process coordinator
scalable. The design must first define how two workers coordinate on one call,
how old work becomes invalid, and how a replacement worker takes over.

### 4.3 Service choices: defaults and conditional candidates

| Capability | Phase 2 default | Conditional candidate and entry condition |
| --- | --- | --- |
| Public runtime | ECS/Fargate when the platform needs an independent worker, internal task, or explicit rollout control | App Runner only if the service is proven stateless HTTP, has no internal worker requirement, and its managed boundary is valuable enough to justify the persistence work |
| Public ingress | HTTPS termination with ALB + ACM when Fargate is selected | WAF only after the threat model and rate-limit requirements justify it; App Runner's ingress is an alternative, not an additional layer by default |
| Durable persistence | RDS PostgreSQL as the small-scale baseline | Aurora PostgreSQL only when availability, scaling, or measured cost evidence exceeds the RDS baseline |
| Hot per-call state | No independent cache initially; use the durable/coordination contract if its latency meets the target | ElastiCache for Valkey/Redis when hot state is rebuildable and latency tests justify it; MemoryDB only when a durable in-memory authority is explicitly required |
| Event transport | No independent event stream initially | Kinesis for ordered, replayable continuous streams; EventBridge for routed notifications and fan-out. Choose per event type, and verify the selected bus/target ordering behavior rather than relying on a platform-wide rule |
| Guidance retrieval | Existing retrieval port and deterministic local/reference implementation | OpenSearch when indexing, query, and corpus lifecycle need direct control; Bedrock Knowledge Bases when managed ingestion/retrieval reduces justified operational work |
| Model explanation | Bedrock adapter as one bounded real-model candidate | An external governed adapter only when its region, privacy, timeout, cost, and evidence contract are equivalent |
| Speech input | No speech service until real audio is a test requirement | Transcribe Streaming when audio latency, retention, and fallback are specified |
| Sentiment enrichment | Existing deterministic taxonomy remains the reference | Comprehend only after a task-level evaluation proves its language/aspect behavior; it is not a default multi-language implementation |
| Speech output | Not in the default scope | Polly only if the product adds a real synthesized-voice output requirement |
| Identity and secrets | Workload IAM roles plus a real user authentication boundary before non-synthetic data | Cognito or external OIDC according to the agent/supervisor and tenant model; Secrets Manager for runtime secrets |
| Observability and delivery | The minimum controls ship with each increment | CloudWatch/OpenTelemetry, GitHub OIDC, dashboards, and alarms expand only with the corresponding runtime and data boundary |

Separate UI and headless tasks, a permanent load-test service, Polly, and an
independent event stream are therefore candidates, not Phase 2 prerequisites.

### 4.4 Migration order

1. **Authority contract:** document durable state, live state, decision
   evidence, revision/state-version rules, ownership, and recovery behavior.
2. **PostgreSQL adapter:** add the storage port, RDS PostgreSQL baseline, and
   migration tests for transactions, idempotency, deletion, and restore.
3. **Cross-process coordination:** prove two workers handling one call, an old
   worker returning late, complaint reopen during an update, and deletion
   racing with background writes. Do not move to a multi-task runtime before
   these tests pass.
4. **Identity, secrets, and transport:** add workload roles, Secrets Manager,
   HTTPS, and agent/supervisor authorization. These are necessary gates for
   any non-synthetic data, not proof that the data policy is complete.
5. **Managed runtime:** move the proven coordinator to Fargate, or select App
   Runner only if its stateless HTTP conditions are satisfied. Verify rolling
   deployment, task exit, takeover, health, and rollback behavior.
6. **Measured hot state and events:** add Valkey/Redis, Kinesis, EventBridge,
   or no additional service according to the finalized semantic and latency
   requirements.
7. **AI adapters:** add Bedrock first as a bounded explanation adapter; add
   Transcribe only with an audio test plan and evaluate Comprehend separately.
   Keep deterministic fallbacks and evidence labels.
8. **Managed retrieval:** place OpenSearch or Knowledge Bases behind the
   existing retrieval port only after corpus ownership, permissions, versioning,
   deletion, and citation contracts are accepted.

Each increment must have a separate acceptance suite that proves the
cross-boundary invariant it introduces. Green infrastructure synthesis alone
is not acceptance.

### 4.5 Event semantics

Event services are selected by event meaning, not by a platform-wide
Kinesis-versus-EventBridge rule:

| Event type | Required semantics | Candidate only after the requirement is proven |
| --- | --- | --- |
| Transcript/revision | Ordering, duplicate handling, replay, consumer position, and stale-result rejection | Kinesis or a simpler durable application boundary |
| Post-call job | Retry, failure isolation, idempotency, and completion evidence | A queue/worker mechanism selected with the job contract |
| Business notification | Routing, subscriptions, and delivery policy | EventBridge or an equivalent notification boundary |
| UI update | Client ordering, state recovery, and browser acknowledgement | The existing application delivery model; a message bus is not business authority |

The selected service must not replace application-level revision, state
version, idempotency, or old-result invalidation. If EventBridge is evaluated,
the exact bus, target, and subscriber topology must be verified against the
required ordering and grouping behavior.

### 4.6 Retrieval and Knowledge Bases boundary

OpenSearch is an indexing/search implementation; Bedrock Knowledge Bases is a
managed ingestion and retrieval layer that may use OpenSearch or another
backing store. They are not mutually exclusive choices at the same layer.

The decision is therefore:

- use direct OpenSearch when the platform must control ingestion, chunking,
  index versions, filtering, and query behavior;
- use Knowledge Bases when managed ingestion and retrieval provide enough
  value and its permission, version, deletion, and citation behavior can be
  verified;
- keep either implementation behind the existing retrieval port.

Knowledge Bases must not bypass deterministic commercial policy, authorization,
or server publication checks. Every returned guidance item must be traceable to
an allowed source/version, and stale or deleted guidance must not be returned.

### 4.7 Per-increment operational and cost contract

Operations are delivered with the increment that introduces the boundary:

| Increment | Required controls before acceptance |
| --- | --- |
| Database | Migration rollback, backup, restore evidence, deletion behavior, and tenant-scope checks |
| Task scaling/runtime | Concurrency limit, health/readiness checks, rollout and rollback steps, and cost ceiling |
| Model adapter | Timeout, quota/budget limit, redacted logs, fallback, and evidence labeling |
| Event or job transport | Retry, dead-letter/failure visibility, idempotency, replay/retention decision, and teardown |
| Audio | Retention, deletion, access scope, latency budget, and failure fallback |
| Retrieval | Permission filtering, version switch, deletion propagation, citation, and index cost boundary |

HTTPS and real identity are necessary before non-synthetic data but are not
sufficient. Purpose, retention, deletion, audit, and recovery approval remain
separate gates.

## 5. Security and cost guardrails

### Phase 1

- Use a non-root AWS identity for CLI/CDK operations.
- Keep the demo CIDR narrow, normally a `/32`.
- The stack rejects `0.0.0.0/0` and configures standard T3 CPU-credit mode;
  stop the instance when it is not being tested.
- Do not put credentials in the image, repository, or GitHub Actions secrets.
- Use synthetic data only.
- Keep the ECR repository retained deliberately, and document its cleanup.
- Destroying the demo stack deletes the instance, root EBS volume, SQLite
  runtime data, and demo log group; the retained ECR repository and any CDK
  bootstrap resources require a separate cleanup decision.
- Review Cost Management after deployment and destroy the demo stack when it
  is not needed.

### Phase 2

- No public database, cache, stream, or search endpoint.
- Prefer private subnets; compare VPC endpoint and NAT cost against the
  actual service set and usage pattern instead of assuming either is cheaper.
- Require HTTPS and real identity before any non-synthetic data.
- Add resource tags, budgets, anomaly alerts, and log retention with the first
  resource in each increment; add backup, deletion protection, and recovery
  evidence with the first durable store.
- Define data residency, retention, deletion, and audit requirements before
  enabling audio or transcript ingestion.
- Classify each Phase 2 service as default, conditional, or out of the current
  scope, and record the teardown path for every conditional resource.

### Phase 2 cost scenarios

Gate C requires estimates and teardown steps for all three operating modes:

| Scenario | Required cost evidence |
| --- | --- |
| One two-hour demonstration | Which resources are created only for the window, what survives teardown, and who confirms cleanup |
| One week of intermittent development | Which services charge while idle, how long they may remain paused, and how they are automatically or manually resumed |
| Continuous pilot | Fixed foundation cost, peak capacity cost, and incremental cost per completed call |

Serverless or autoscaling labels do not establish a zero-idle-cost design.
Storage, public ingress, load balancers, databases, caches, search, logging,
and VPC connectivity must be included in the estimate.

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

- Authority, persistence, cross-process coordination, identity, event delivery,
  and retrieval contracts are reviewed.
- Every proposed service is classified as a default, conditional candidate, or
  out of scope, with an entry condition and acceptance evidence.
- The three cost scenarios in Section 5 are estimated, including idle cost and
  teardown strategy.
- The production-shaped threat model and data classification are approved.
- Each Phase 2 increment has an owner, rollback path, and acceptance tests.

## 7. Open decisions for independent review

The architecture review should explicitly challenge these choices:

1. Is EC2 the right Phase 1 runtime, or is App Runner worth its managed HTTPS
   boundary despite the persistence refactor it would require?
2. Does the public runtime require Fargate's worker/task control, or do the
   stateless HTTP conditions make App Runner the simpler boundary?
3. Which state and decision contracts must pass the two-worker race tests
   before any runtime migration?
4. Does the durable-store baseline need only RDS PostgreSQL, or does measured
   availability, scale, or cost evidence justify Aurora PostgreSQL?
5. Is hot state rebuildable enough to avoid a cache, or does measured latency
   justify ElastiCache/Valkey? Is a durable in-memory authority actually
   required before considering MemoryDB?
6. For each event type, are ordering/replay, job retry, notification routing,
   or UI recovery the actual requirement, and which service satisfies it?
7. Should guidance use direct OpenSearch control or managed Knowledge Bases,
   and how will permissions, versions, deletion, and citations be proven?
8. Which AI adapter is needed next: Bedrock explanation, Transcribe audio, or
   evaluated Comprehend enrichment? Is there a real requirement for Polly?
9. What is the smallest acceptable identity boundary for an agent versus a
   supervisor, and how will tenant scope be enforced end to end?
10. What must be redacted from logs, traces, event payloads, audio, and model
    requests, and what are the three-mode cost and teardown results?

## 8. Deliverables

This specification governs the current AWS foundation PR and the subsequent
implementation PRs. The immediate deliverable is Phase 1 cloud validation. A
Phase 2 implementation must not be started from this document alone; the
open decisions above must be resolved in a reviewed design update first.
