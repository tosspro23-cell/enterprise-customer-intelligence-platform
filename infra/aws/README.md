# AWS demo deployment

This directory contains the first cloud deployment foundation for the local
reference slice. It intentionally preserves the current application contract:
one FastAPI process, one container, and SQLite in a host runtime directory on
an encrypted EBS root volume.

It is suitable for synthetic-data demos and cloud testing. It is not a
production topology. The application still uses the demo principal model and
does not yet provide real enterprise identity, TLS, multi-instance state
consistency, or a managed relational/event store.

## Prerequisites

- AWS CLI with credentials for the target account and region.
- Docker Desktop running locally.
- Node.js and AWS CDK CLI v2.
- Python 3.12+.

The repository currently has the AWS CLI and CDK CLI installed locally, but the
AWS CLI must be authenticated before deployment. Prefer `aws login` for the
current AWS CLI flow, or use the account's normal profile configuration.

## Deploy

Choose a region and restrict the demo endpoint to your current public IP when
possible. The `/32` restriction is important because the first deployment is
HTTP-only and intended for synthetic data.

```bash
export AWS_REGION=us-east-1
export DEMO_CIDR="203.0.113.10/32"  # replace with your public IP/CIDR
export IMAGE_TAG="$(git rev-parse --short HEAD)"

cd infra/aws
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cdk bootstrap
cdk deploy CustomerIntelligenceRepository \
  --require-approval broadening
```

Read the `RepositoryUri` output, then build and push the image from the
repository root:

```bash
export REPOSITORY_URI="<RepositoryUri output>"
cd ../..
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "${REPOSITORY_URI%%/*}"
docker build --platform linux/amd64 -t "$REPOSITORY_URI:$IMAGE_TAG" .
docker push "$REPOSITORY_URI:$IMAGE_TAG"
```

Deploy the host only after the image exists in ECR:

```bash
cd infra/aws
cdk deploy CustomerIntelligenceDemo \
  --context image_tag="$IMAGE_TAG" \
  --context allowed_cidr="$DEMO_CIDR" \
  --require-approval broadening
```

The stack outputs the Elastic-IP-backed HTTP URL, instance ID, and CloudWatch
log group. The URL remains the same across normal application image rollouts
and instance stop/start operations while the demo stack and Elastic IP exist.
The host is managed through Systems Manager; no inbound SSH rule or SSH key is
created.

The current deployed Phase One URL is
[`http://98.95.194.236`](http://98.95.194.236). The Security Group allows HTTP
only from the operator-provided CIDR and rejects an open `0.0.0.0/0` rule. Do
not widen the CIDR for a customer demo without adding HTTPS, real identity,
and application-level rate limiting.

Treat a successful CloudFormation deployment as infrastructure creation, not
as proof that the demo is ready. Complete the following smoke check before
sharing the URL:

```bash
export DEMO_URL="<DemoUrl output>"
curl --fail "$DEMO_URL/api/health"
curl --fail "$DEMO_URL/api/demo/scenarios" \
  | python3 -c 'import json, sys; assert len(json.load(sys.stdin)["scenarios"]) == 3'
aws ssm describe-instance-information --region "$AWS_REGION"
```

Then exercise one complete synthetic call through start, transcript, end, and
post-call, read the customer history, restart the container through SSM, and
read that history again. This verifies the EBS-backed SQLite path rather than
only proving that the container started. A container/process restart preserves
completed history but resets any in-memory live call; restart the scenario if
the live demo was interrupted.

## Update an existing host

EC2 user data is an initial bootstrap mechanism used only when the host is first
created. It is not the image rollout mechanism, and re-running `cdk deploy`
does not by itself replace the image on an existing host. After pushing a new
commit-tagged image to the immutable ECR repository, use the checked-in SSM
update script so the existing host pulls and replaces the container while
preserving the runtime directory and verifying the running image digest:

```bash
export INSTANCE_ID="<InstanceId output>"
export LOG_GROUP_NAME="<LogGroupName output>"
export IMAGE_TAG="$(git rev-parse --short HEAD)"
export REPOSITORY_URI="<RepositoryUri output>"
./infra/aws/update-demo.sh
```

The script reports the remote command status and stdout/stderr. Re-run the
smoke check after every update; do not infer a successful image rollout from a
successful `aws ssm send-command` request alone.

## Teardown and cost control

To stop compute charges after a demo, destroy the demo stack. Stopping the
instance instead preserves the root EBS volume and SQLite data but can still
incur storage, Elastic IP/public IPv4, and logging charges. The ECR
repository is intentionally retained by the repository stack so images are not
deleted accidentally. Destroying the demo stack releases the Elastic IP and
deletes the instance, its root EBS volume, the runtime SQLite database, and the
demo log group.

```bash
cdk destroy CustomerIntelligenceDemo
```

Delete the repository stack only after explicitly deciding that the image
history is no longer needed. The repository has a retain policy and must be
cleaned up separately if its images should be removed. A CDK bootstrap stack
may also remain for other CDK applications; do not delete it blindly. Review
AWS Billing and Free Tier usage after each deployment; credits are a budget,
not proof that a resource is cost-free.

## Next cloud increments

1. Add a real authentication boundary and HTTPS before any non-synthetic data.
2. Replace SQLite with a managed persistence adapter and add migration tests.
3. Move the container to ECS/Fargate or App Runner once multi-instance
   semantics and operational telemetry are ready.
4. Add an approval-gated deployment workflow; this PR deliberately does not
   store AWS credentials or deploy automatically from GitHub Actions.
