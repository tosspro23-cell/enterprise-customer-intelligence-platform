from pathlib import Path


UPDATE_SCRIPT = (
    Path(__file__).resolve().parents[2] / "infra" / "aws" / "update-demo.sh"
)


def test_update_script_verifies_the_digest_of_the_running_image() -> None:
    script = UPDATE_SCRIPT.read_text()

    # Docker exposes RepoDigests on images. The previous implementation queried
    # that field on the container and failed after replacing the container.
    assert "docker inspect --format '{{.Image}}' customer-intelligence" in script
    assert "docker image inspect" in script
    assert (
        "docker inspect --format '{{index .RepoDigests 0}}' customer-intelligence"
        not in script
    )
