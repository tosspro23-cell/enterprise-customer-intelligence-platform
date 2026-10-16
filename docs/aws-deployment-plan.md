# AWS deployment plan

## Decision for the first cloud increment

Use a single Amazon EC2 `t3.micro` host running the existing FastAPI service
in Docker. Store the SQLite database under a host runtime directory on the
instance's 20 GiB encrypted gp3 root EBS volume. Use
Amazon ECR for the image, CloudWatch Logs for application output, and Systems
Manager Session Manager for administrative access.

This is the narrowest deployment that preserves the current reference-slice
semantics. It gives the Workbench a reachable temporary endpoint for cloud
testing and customer demonstrations without prematurely changing the
concurrency and persistence model. The public IP may change after a
stop/start, so this is not a stable production URL.

## Why this target first

The current platform is a modular monolith with an in-process coordinator and
SQLite. Moving it directly to a multi-task service would create two unrelated
changes at once: cloud infrastructure and a distributed persistence contract.
The EC2 container target isolates the first change and keeps the existing
correctness tests meaningful.

The selected stack also fits the account constraints better than an always-on
load-balanced Fargate service. The exact Free Tier eligibility depends on the
account creation date and account plan, so the deployment must still be
checked in Billing. `t3.micro` and gp3 are represented as Free Tier-eligible
choices in the current AWS documentation, but this is not a guarantee that
the account will incur zero charges.

## Explicit boundaries

This deployment is for synthetic data only. It is not ready for production or
real customer data because:

- the browser uses the reference demo principal model rather than enterprise
  identity;
- the first endpoint is HTTP-only and should be CIDR-restricted;
- SQLite is durable across container restarts on one host but is not safe for
  horizontal scaling, instance replacement, or deletion;
- a process/container restart preserves completed history but intentionally
  loses in-memory live-call state; the active scenario must be restarted;
- there is no managed failover, backup policy, or disaster-recovery runbook;
- deployment is manual and approval-gated rather than an unattended pipeline.

The CDK stack creates no SSH ingress. Operators use Session Manager, and the
only inbound rule is the explicitly supplied HTTP CIDR for the demo endpoint.

## Alternatives considered

| Target | Strength | Why it is not the first increment |
| --- | --- | --- |
| EC2 + Docker + EBS | Preserves SQLite and has predictable low idle cost | Manual operations; single host |
| App Runner | Managed HTTPS and simple container operations | Requires a separate durable store; provisioned memory is billed while idle |
| ECS/Fargate + ALB | Better production-shaped service boundary | ALB/networking cost and distributed persistence are premature here |
| Lambda/API Gateway | Very low idle compute for request-driven traffic | Requires a persistence and adapter refactor; poor fit for the current in-process coordinator |
| Lightsail container | Simple predictable operations | Charges continue while the service is disabled; less aligned with the intended AWS learning path |

## Promotion path

The first PR adds container and CDK foundations plus an explicit SSM update
path. After a successful cloud smoke test, the next PR should introduce a
persistence port with RDS PostgreSQL as the baseline, then define and test
cross-process state ownership and coordination. A real authentication and TLS
boundary must precede any non-synthetic data. Only after those contracts are
tested should the runtime move to ECS/Fargate or, if it is truly stateless
HTTP, App Runner. Caches, event streams, and managed retrieval remain
conditional follow-up increments.

## Operational acceptance for this PR

- `docker build` succeeds from a clean checkout.
- The image starts with the deployment mount layout, exposes all three scenario
  fixtures, and creates the SQLite file in the host runtime directory.
- The image health check returns `{"status":"ok"}`.
- A minimal call can be started, receive a transcript segment, end, and run
  post-call processing; the resulting history record is readable after the
  container is restarted with the same mounted runtime directory.
- `cdk synth` produces both repository and demo stacks without AWS credentials.
- The EC2 security group has only the explicit HTTP CIDR and no SSH rule.
- The instance role grants Session Manager, ECR read, and scoped CloudWatch log
  write permissions.
- The SQLite path is on the host runtime directory, while read-only scenario
  fixtures remain visible under the image's `/app/data` path.
- The checked-in SSM update path replaces the running image and reports remote
  command failure instead of treating command submission as deployment success.
- After an image update, the same health, scenario, and completed-history
  smoke must pass, and the actual running image digest must be recorded. The
  digest check resolves the image ID from the running container and inspects
  the image object; `RepoDigests` is not a container field.
- The README documents deployment, teardown, and the non-production boundary.

## Observed Phase 1 account checks

The following read-only checks were run on 2026-10-16 after the image rollout.
They are account evidence for this demo, not a promise of continuing zero cost:

- Cost Explorer returned a current-month-to-date `UnblendedCost` of
  `-0.0000000183 USD` for 2026-10-01 through 2026-10-17. The negative value is
  consistent with an account credit or adjustment; it must not be interpreted
  as proof that future usage is free.
- The Free Tier API returned 13 account usage records. The returned snapshot did
  not expose an EC2, EBS, or ECR allowance, so coverage of those resources is
  not treated as verified. Billing and Free Tier usage should continue to be
  checked in the AWS console while the demo remains deployed.
- The demo remains synthetic-only and should be destroyed when it is not needed;
  the retained ECR repository and images are a separate storage-cost decision.
