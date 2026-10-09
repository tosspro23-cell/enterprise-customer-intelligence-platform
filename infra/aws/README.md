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

The stack outputs the temporary HTTP URL, instance ID, and CloudWatch log
group. The host is managed through Systems Manager; no inbound SSH rule or SSH
key is created.

## Teardown and cost control

To stop compute charges after a demo, destroy the demo stack. The ECR
repository is intentionally retained by the repository stack so images are not
deleted accidentally.

```bash
cdk destroy CustomerIntelligenceDemo
```

Delete the repository stack only after explicitly deciding that the image
history is no longer needed. Review AWS Billing and Free Tier usage after each
deployment; credits are a budget, not proof that a resource is cost-free.

## Next cloud increments

1. Add a real authentication boundary and HTTPS before any non-synthetic data.
2. Replace SQLite with a managed persistence adapter and add migration tests.
3. Move the container to ECS/Fargate or App Runner once multi-instance
   semantics and operational telemetry are ready.
4. Add an approval-gated deployment workflow; this PR deliberately does not
   store AWS credentials or deploy automatically from GitHub Actions.
