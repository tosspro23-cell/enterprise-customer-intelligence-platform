# AWS deployment plan

## Decision for the first cloud increment

Use a single Amazon EC2 `t3.micro` host running the existing FastAPI service
in Docker. Store the SQLite database under a host runtime directory on the
instance's 20 GiB encrypted gp3 root EBS volume. Use
Amazon ECR for the image, CloudWatch Logs for application output, and Systems
Manager Session Manager for administrative access.

This is the narrowest deployment that preserves the current reference-slice
semantics. It gives the Workbench a stable HTTP endpoint for cloud testing and
customer demonstrations without prematurely changing the concurrency and
persistence model. The endpoint is backed by a stack-owned Elastic IP, so
normal application image rollouts and instance stop/start operations retain
the same address while the demo stack exists. Destroying the stack releases
the address; it is not a permanent production URL or domain name.

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
- the Elastic IP is a stable demo address, not TLS, DNS, or a production ingress
  boundary;
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
- The CI suite executes the update path against a local fake AWS CLI and covers
  successful rollout, remote SSM failure, and running-image digest mismatch.
- After an image update, the same health, scenario, and completed-history
  smoke must pass, and the actual running image digest must be recorded. The
  digest check resolves the image ID from the running container and inspects
  the image object; `RepoDigests` is not a container field.
- The README documents deployment, teardown, and the non-production boundary.
- The demo URL is backed by a stack-owned Elastic IP and remains stable while
  the demo stack exists; teardown releases that address.

### Deployment identity closeout boundary

The Phase One deployment identity is a non-root IAM user, but it currently has
the broad `AdministratorAccess` managed policy so that the initial, manually
approved CDK deployment could be completed without hiding a missing service
permission. This is an operational convenience, not a least-privilege design
and not permission to deploy arbitrary future infrastructure without review.

Before Phase Two or any real customer data, replace this broad policy with a
scoped deployment role and an explicitly reviewed trust path. The replacement
must be derived from the actual CDK bootstrap, CloudFormation execution, ECR,
SSM, CloudWatch, EC2, and IAM-pass-role actions used by the selected stacks;
guessing a short allow-list would risk either a broken deployment or a false
security claim. Phase One is therefore accepted as synthetic-only with this
identity hardening recorded as a required follow-up.

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
  The Elastic IP is also a billable public IPv4 resource and is released by
  destroying the demo stack.
