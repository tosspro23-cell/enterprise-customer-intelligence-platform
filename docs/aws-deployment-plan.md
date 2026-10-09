# AWS deployment plan

## Decision for the first cloud increment

Use a single Amazon EC2 `t3.micro` host running the existing FastAPI service
in Docker. Store the SQLite database under a host runtime directory on the
instance's 20 GiB encrypted gp3 root EBS volume. Use
Amazon ECR for the image, CloudWatch Logs for application output, and Systems
Manager Session Manager for administrative access.

This is the narrowest deployment that preserves the current reference-slice
semantics. It gives the Workbench a stable URL for cloud testing and customer
demonstrations without prematurely changing the concurrency and persistence
model.

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

The first PR adds container and CDK foundations only. After a successful cloud
smoke test, the next PR should introduce a persistence abstraction that can be
backed by DynamoDB or Aurora PostgreSQL, then add a real authentication
boundary and TLS. Only after those contracts are tested should the runtime move
to ECS/Fargate or App Runner.

## Operational acceptance for this PR

- `docker build` succeeds from a clean checkout.
- The image health check returns `{"status":"ok"}`.
- `cdk synth` produces both repository and demo stacks without AWS credentials.
- The EC2 security group has only the explicit HTTP CIDR and no SSH rule.
- The instance role grants Session Manager, ECR read, and scoped CloudWatch log
  write permissions.
- The SQLite path is on the host runtime directory, while read-only scenario
  fixtures remain visible under the image's `/app/data` path.
- The README documents deployment, teardown, and the non-production boundary.
