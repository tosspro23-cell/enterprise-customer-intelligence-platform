from pathlib import Path
import os
import stat
import subprocess
import tempfile

import pytest


UPDATE_SCRIPT = (
    Path(__file__).resolve().parents[2] / "infra" / "aws" / "update-demo.sh"
)


def test_update_script_verifies_the_digest_of_the_running_image() -> None:
    script = UPDATE_SCRIPT.read_text()

    # Docker exposes RepoDigests on images. The previous implementation queried
    # that field on the container and failed after replacing the container.
    assert "docker inspect --format '{{.Image}}' customer-intelligence" in script
    assert "docker image inspect" in script
    assert 'json.dumps({"commands": [' in script
    assert '--parameters "$commands_json"' in script
    assert '--parameters "$verify_parameters"' in script
    assert 'LLM_PROVIDER="${LLM_PROVIDER:-fake}"' in script
    assert 'BEDROCK_MODEL_ID="${BEDROCK_MODEL_ID:-us.amazon.nova-micro-v1:0}"' in script
    assert "--env AWS_REGION={region}" in script
    assert (
        "docker inspect --format '{{index .RepoDigests 0}}' customer-intelligence"
        not in script
    )


FAKE_AWS = r'''#!/usr/bin/env python3
import json
import os
import sys


args = sys.argv[1:]
mode = os.environ.get("FAKE_AWS_MODE", "success")


def option(name: str) -> str:
    index = args.index(name)
    return args[index + 1]


def validate_parameters() -> None:
    payload = json.loads(option("--parameters"))
    assert isinstance(payload["commands"], list)
    assert payload["commands"]


service = args[0]
operation = args[1]

if service == "ecr" and operation == "describe-images":
    print("sha256:expected")
    raise SystemExit(0)

if service == "ssm" and operation == "send-command":
    validate_parameters()
    print("verify" if option("--comment").startswith("Verify") else "rollout")
    raise SystemExit(0)

if service == "ssm" and operation == "wait":
    if mode == "remote_failed" and option("--command-id") == "rollout":
        raise SystemExit(1)
    print("success")
    raise SystemExit(0)

if service == "ssm" and operation == "get-command-invocation":
    command_id = option("--command-id")
    query = option("--query")
    if query == "Status":
        print("Failed" if mode == "remote_failed" and command_id == "rollout" else "Success")
    elif query == "StandardOutputContent":
        digest = "sha256:wrong" if mode == "digest_mismatch" else "sha256:expected"
        print(f"registry.example/customer-intelligence@{digest}")
    else:
        print(json.dumps({"status": "Success", "stdout": "", "stderr": ""}))
    raise SystemExit(0)

raise SystemExit(f"unexpected fake AWS call: {args!r}")
'''


@pytest.mark.parametrize(
    ("mode", "expected_returncode"),
    [
        ("success", 0),
        ("remote_failed", 1),
        ("digest_mismatch", 1),
    ],
)
def test_update_script_reports_rollout_and_digest_outcomes(
    mode: str, expected_returncode: int
) -> None:
    """Exercise the script boundary without requiring AWS credentials.

    The fake CLI models the AWS responses that matter to the script: ECR tag
    lookup, SSM command execution, remote command failure, and digest
    verification. This keeps the failure paths in the same CI suite as the
    application tests instead of testing only the shell source text.
    """
    with tempfile.TemporaryDirectory() as temporary_directory:
        fake_bin = Path(temporary_directory) / "aws"
        fake_bin.write_text(FAKE_AWS)
        fake_bin.chmod(fake_bin.stat().st_mode | stat.S_IXUSR)

        environment = os.environ.copy()
        environment.update(
            {
                "AWS_REGION": "us-east-1",
                "INSTANCE_ID": "i-test",
                "REPOSITORY_URI": "registry.example/customer-intelligence",
                "IMAGE_TAG": "test-tag",
                "LOG_GROUP_NAME": "/demo/customer-intelligence",
                "FAKE_AWS_MODE": mode,
                "PATH": f"{temporary_directory}{os.pathsep}{environment['PATH']}",
            }
        )
        result = subprocess.run(
            ["bash", str(UPDATE_SCRIPT)],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

    assert result.returncode == expected_returncode, result.stdout + result.stderr
    if mode == "remote_failed":
        assert "SSM waiter reported a non-success terminal state" in result.stderr
    if mode == "digest_mismatch":
        assert "Running image digest mismatch" in result.stderr
