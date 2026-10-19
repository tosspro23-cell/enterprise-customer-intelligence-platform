#!/usr/bin/env bash

set -euo pipefail

: "${AWS_REGION:?Set AWS_REGION to the deployed stack region}"
: "${INSTANCE_ID:?Set INSTANCE_ID from the CustomerIntelligenceDemo output}"
: "${REPOSITORY_URI:?Set REPOSITORY_URI from the CustomerIntelligenceRepository output}"
: "${IMAGE_TAG:?Set IMAGE_TAG to the pushed ECR tag}"
: "${LOG_GROUP_NAME:?Set LOG_GROUP_NAME from the CustomerIntelligenceDemo output}"

LLM_PROVIDER="${LLM_PROVIDER:-fake}"
BEDROCK_MODEL_ID="${BEDROCK_MODEL_ID:-us.amazon.nova-micro-v1:0}"
AUTH_MODE="${AUTH_MODE:-demo}"
AUTH_CUSTOMER_IDS="${AUTH_CUSTOMER_IDS:-C001,C002}"
COGNITO_ISSUER="${COGNITO_ISSUER:-}"
COGNITO_AUDIENCE="${COGNITO_AUDIENCE:-}"
COGNITO_DEFAULT_TENANT_ID="${COGNITO_DEFAULT_TENANT_ID:-demo-tenant}"
COGNITO_DEFAULT_PURPOSE="${COGNITO_DEFAULT_PURPOSE:-customer-service}"
CORS_ALLOWED_ORIGINS="${CORS_ALLOWED_ORIGINS:-*}"
RATE_LIMIT_REQUESTS_PER_MINUTE="${RATE_LIMIT_REQUESTS_PER_MINUTE:-120}"
case "$LLM_PROVIDER" in
  fake|bedrock) ;;
  *) echo "LLM_PROVIDER must be fake or bedrock" >&2; exit 1 ;;
esac
case "$AUTH_MODE" in
  demo) ;;
  cognito)
    IFS=',' read -r -a cors_origins <<< "$CORS_ALLOWED_ORIGINS"
    wildcard_cors=false
    for origin in "${cors_origins[@]}"; do
      if [[ "$origin" == "*" ]]; then
        wildcard_cors=true
      fi
    done
    if [[ -z "$COGNITO_ISSUER" || -z "$COGNITO_AUDIENCE" || -z "$CORS_ALLOWED_ORIGINS" || "$wildcard_cors" == true ]]; then
      echo "COGNITO_ISSUER, COGNITO_AUDIENCE, and a concrete CORS_ALLOWED_ORIGINS value are required for AUTH_MODE=cognito" >&2
      exit 1
    fi
    ;;
  *) echo "AUTH_MODE must be demo or cognito" >&2; exit 1 ;;
esac
if ! [[ "$RATE_LIMIT_REQUESTS_PER_MINUTE" =~ ^[1-9][0-9]*$ ]]; then
  echo "RATE_LIMIT_REQUESTS_PER_MINUTE must be a positive integer" >&2
  exit 1
fi

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

commands_json="$(python3 - "$AWS_REGION" "$registry_host" "$image_uri" "$LOG_GROUP_NAME" "$LLM_PROVIDER" "$BEDROCK_MODEL_ID" "$AUTH_MODE" "$AUTH_CUSTOMER_IDS" "$COGNITO_ISSUER" "$COGNITO_AUDIENCE" "$COGNITO_DEFAULT_TENANT_ID" "$COGNITO_DEFAULT_PURPOSE" "$CORS_ALLOWED_ORIGINS" "$RATE_LIMIT_REQUESTS_PER_MINUTE" <<'PY'
import json
import shlex
import sys

(
    region,
    registry_host,
    image_uri,
    log_group_name,
    llm_provider,
    bedrock_model_id,
    auth_mode,
    auth_customer_ids,
    cognito_issuer,
    cognito_audience,
    cognito_default_tenant_id,
    cognito_default_purpose,
    cors_allowed_origins,
    rate_limit_requests_per_minute,
) = sys.argv[1:]


def env_arg(name: str, value: str) -> str:
    return f"--env {shlex.quote(f'{name}={value}')}"


def quoted(value: str) -> str:
    return shlex.quote(value)


print(json.dumps({"commands": [
    "set -euo pipefail",
    f"aws ecr get-login-password --region {quoted(region)} | docker login --username AWS --password-stdin {quoted(registry_host)}",
    f"docker pull {quoted(image_uri)}",
    "docker rm --force customer-intelligence || true",
    (
        "docker run --detach --name customer-intelligence --restart unless-stopped "
        f"--publish 80:8765 {env_arg('DATABASE_PATH', '/var/lib/customer-intelligence/platform.db')} "
        f"{env_arg('AWS_REGION', region)} {env_arg('LLM_PROVIDER', llm_provider)} "
        f"{env_arg('BEDROCK_MODEL_ID', bedrock_model_id)} "
        f"{env_arg('AUTH_MODE', auth_mode)} {env_arg('AUTH_CUSTOMER_IDS', auth_customer_ids)} "
        f"{env_arg('COGNITO_ISSUER', cognito_issuer)} {env_arg('COGNITO_AUDIENCE', cognito_audience)} "
        f"{env_arg('COGNITO_DEFAULT_TENANT_ID', cognito_default_tenant_id)} "
        f"{env_arg('COGNITO_DEFAULT_PURPOSE', cognito_default_purpose)} "
        f"{env_arg('CORS_ALLOWED_ORIGINS', cors_allowed_origins)} "
        f"{env_arg('RATE_LIMIT_REQUESTS_PER_MINUTE', rate_limit_requests_per_minute)} "
        "--volume /var/lib/customer-intelligence:/var/lib/customer-intelligence "
        f"--log-driver awslogs --log-opt {quoted(f'awslogs-region={region}')} "
        f"--log-opt {quoted(f'awslogs-group={log_group_name}')} "
        f"--log-opt awslogs-stream=customer-intelligence {quoted(image_uri)}"
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
