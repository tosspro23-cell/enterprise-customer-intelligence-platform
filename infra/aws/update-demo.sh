#!/usr/bin/env bash

set -euo pipefail

: "${AWS_REGION:?Set AWS_REGION to the deployed stack region}"
: "${INSTANCE_ID:?Set INSTANCE_ID from the CustomerIntelligenceDemo output}"
: "${REPOSITORY_URI:?Set REPOSITORY_URI from the CustomerIntelligenceRepository output}"
: "${IMAGE_TAG:?Set IMAGE_TAG to the pushed ECR tag}"
: "${LOG_GROUP_NAME:?Set LOG_GROUP_NAME from the CustomerIntelligenceDemo output}"

registry_host="${REPOSITORY_URI%%/*}"
image_uri="${REPOSITORY_URI}:${IMAGE_TAG}"

command_id="$({
  aws ssm send-command \
    --region "$AWS_REGION" \
    --instance-ids "$INSTANCE_ID" \
    --document-name AWS-RunShellScript \
    --comment "Update customer intelligence demo to ${IMAGE_TAG}" \
    --parameters "commands=set -euo pipefail,aws ecr get-login-password --region ${AWS_REGION} | docker login --username AWS --password-stdin ${registry_host},docker pull ${image_uri},docker rm --force customer-intelligence || true,docker run --detach --name customer-intelligence --restart unless-stopped --publish 80:8765 --env DATABASE_PATH=/var/lib/customer-intelligence/platform.db --volume /var/lib/customer-intelligence:/var/lib/customer-intelligence --log-driver awslogs --log-opt awslogs-region=${AWS_REGION} --log-opt awslogs-group=${LOG_GROUP_NAME} --log-opt awslogs-stream=customer-intelligence ${image_uri}" \
    --query Command.CommandId \
    --output text
})"

echo "Waiting for SSM command ${command_id} on ${INSTANCE_ID}"
aws ssm wait command-executed \
  --region "$AWS_REGION" \
  --command-id "$command_id" \
  --instance-id "$INSTANCE_ID"

status="$(aws ssm get-command-invocation \
  --region "$AWS_REGION" \
  --command-id "$command_id" \
  --instance-id "$INSTANCE_ID" \
  --query Status \
  --output text)"

aws ssm get-command-invocation \
  --region "$AWS_REGION" \
  --command-id "$command_id" \
  --instance-id "$INSTANCE_ID" \
  --query '{status:Status,stdout:StandardOutputContent,stderr:StandardErrorContent}' \
  --output json

if [[ "$status" != "Success" ]]; then
  exit 1
fi
