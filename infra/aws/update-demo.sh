#!/usr/bin/env bash

set -euo pipefail

: "${AWS_REGION:?Set AWS_REGION to the deployed stack region}"
: "${INSTANCE_ID:?Set INSTANCE_ID from the CustomerIntelligenceDemo output}"
: "${REPOSITORY_URI:?Set REPOSITORY_URI from the CustomerIntelligenceRepository output}"
: "${IMAGE_TAG:?Set IMAGE_TAG to the pushed ECR tag}"
: "${LOG_GROUP_NAME:?Set LOG_GROUP_NAME from the CustomerIntelligenceDemo output}"

LLM_PROVIDER="${LLM_PROVIDER:-fake}"
BEDROCK_MODEL_ID="${BEDROCK_MODEL_ID:-us.amazon.nova-micro-v1:0}"
case "$LLM_PROVIDER" in
  fake|bedrock) ;;
  *) echo "LLM_PROVIDER must be fake or bedrock" >&2; exit 1 ;;
esac

registry_host="${REPOSITORY_URI%%/*}"
repository_name="${REPOSITORY_URI#*/}"
image_uri="${REPOSITORY_URI}:${IMAGE_TAG}"
expected_digest="$({
  aws ecr describe-images \
    --region "$AWS_REGION" \
    --repository-name "$repository_name" \
    --image-ids "imageTag=${IMAGE_TAG}" \
    --query 'imageDetails[0].imageDigest' \
    --output text
})"
if [[ -z "$expected_digest" || "$expected_digest" == "None" ]]; then
  echo "ECR image tag ${IMAGE_TAG} was not found in ${repository_name}" >&2
  exit 1
fi

commands_json="$(python3 - "$AWS_REGION" "$registry_host" "$image_uri" "$LOG_GROUP_NAME" "$LLM_PROVIDER" "$BEDROCK_MODEL_ID" <<'PY'
import json
import sys

region, registry_host, image_uri, log_group_name, llm_provider, bedrock_model_id = sys.argv[1:]
print(json.dumps({"commands": [
    "set -euo pipefail",
    f"aws ecr get-login-password --region {region} | docker login --username AWS --password-stdin {registry_host}",
    f"docker pull {image_uri}",
    "docker rm --force customer-intelligence || true",
    (
        "docker run --detach --name customer-intelligence --restart unless-stopped "
        "--publish 80:8765 --env DATABASE_PATH=/var/lib/customer-intelligence/platform.db "
        f"--env AWS_REGION={region} --env LLM_PROVIDER={llm_provider} "
        f"--env BEDROCK_MODEL_ID={bedrock_model_id} "
        "--volume /var/lib/customer-intelligence:/var/lib/customer-intelligence "
        f"--log-driver awslogs --log-opt awslogs-region={region} "
        f"--log-opt awslogs-group={log_group_name} "
        f"--log-opt awslogs-stream=customer-intelligence {image_uri}"
    ),
]}))
PY
)"

wait_for_command() {
  local command_id="$1"
  local wait_status=0
  if aws ssm wait command-executed \
    --region "$AWS_REGION" \
    --command-id "$command_id" \
    --instance-id "$INSTANCE_ID"; then
    :
  else
    wait_status=$?
    echo "SSM waiter reported a non-success terminal state for ${command_id} (exit ${wait_status}); fetching invocation details." >&2
  fi
}

command_id="$({
  aws ssm send-command \
    --region "$AWS_REGION" \
    --instance-ids "$INSTANCE_ID" \
    --document-name AWS-RunShellScript \
    --comment "Update customer intelligence demo to ${IMAGE_TAG}" \
    --parameters "$commands_json" \
    --query Command.CommandId \
    --output text
})"

echo "Waiting for SSM command ${command_id} on ${INSTANCE_ID}"
wait_for_command "$command_id"

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

verify_command_id="$({
  # RepoDigests belongs to the image object, not the container object. Resolve
  # the image ID used by the running container first, then inspect that image.
  verify_parameters="$(python3 <<'PY'
import json

print(json.dumps({"commands": [
    "docker image inspect \"$(docker inspect --format '{{.Image}}' customer-intelligence)\" --format '{{index .RepoDigests 0}}'"
]}))
PY
)"
  aws ssm send-command \
    --region "$AWS_REGION" \
    --instance-ids "$INSTANCE_ID" \
    --document-name AWS-RunShellScript \
    --comment "Verify customer intelligence demo image digest" \
    --parameters "$verify_parameters" \
    --query Command.CommandId \
    --output text
})"

echo "Verifying image digest with SSM command ${verify_command_id}"
wait_for_command "$verify_command_id"

verify_status="$(aws ssm get-command-invocation \
  --region "$AWS_REGION" \
  --command-id "$verify_command_id" \
  --instance-id "$INSTANCE_ID" \
  --query Status \
  --output text)"
running_image_ref="$(aws ssm get-command-invocation \
  --region "$AWS_REGION" \
  --command-id "$verify_command_id" \
  --instance-id "$INSTANCE_ID" \
  --query StandardOutputContent \
  --output text | tr -d '\r\n')"
running_digest="${running_image_ref##*@}"
if [[ "$verify_status" != "Success" || "$running_digest" != "$expected_digest" ]]; then
  echo "Running image digest mismatch: expected ${expected_digest}, got ${running_digest:-<empty>}" >&2
  aws ssm get-command-invocation \
    --region "$AWS_REGION" \
    --command-id "$verify_command_id" \
    --instance-id "$INSTANCE_ID" \
    --query '{status:Status,stdout:StandardOutputContent,stderr:StandardErrorContent}' \
    --output json
  exit 1
fi

echo "Running image digest verified: ${running_digest}"
