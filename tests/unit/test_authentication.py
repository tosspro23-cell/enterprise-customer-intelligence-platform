import pytest

from backend.security.authentication import (
    AGENT_PERMISSIONS,
    AuthenticationError,
    CognitoJWTAuthenticator,
    principal_from_claims,
)


def test_claims_translate_to_scoped_agent_principal() -> None:
    principal = principal_from_claims(
        {
            "sub": "user-123",
            "cognito:groups": ["agent"],
            "custom:tenant_id": "tenant-a",
            "custom:customer_ids": "C001, C009",
        },
        default_customer_ids=frozenset({"C001"}),
    )

    assert principal.principal_id == "oidc:user-123"
    assert principal.tenant_id == "tenant-a"
    assert principal.roles == ("agent",)
    assert principal.permissions == AGENT_PERMISSIONS
    assert principal.allowed_customer_ids == frozenset({"C001", "C009"})


def test_claims_require_a_supported_role() -> None:
    with pytest.raises(AuthenticationError, match="supported platform role"):
        principal_from_claims(
            {"sub": "user-123", "cognito:groups": ["billing"]},
            default_customer_ids=frozenset({"C001"}),
        )


def test_authenticator_hides_decoder_failures() -> None:
    def fail(_: str):
        raise RuntimeError("private key-set detail")

    authenticator = CognitoJWTAuthenticator(
        issuer="https://issuer.example",
        audience="client-id",
        default_customer_ids=frozenset({"C001"}),
        decoder=fail,
    )

    with pytest.raises(AuthenticationError, match="invalid bearer token") as error:
        authenticator.authenticate("opaque-token")
    assert "private key-set detail" not in str(error.value)
