import pytest

from backend.security.authentication import (
    AGENT_PERMISSIONS,
    AuthenticationError,
    CognitoJWTAuthenticator,
    principal_from_claims,
    validate_cognito_audience,
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
        default_tenant_id="tenant-a",
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


def test_claims_cannot_introduce_a_second_tenant_into_single_tenant_store() -> None:
    with pytest.raises(AuthenticationError, match="unsupported tenant scope"):
        principal_from_claims(
            {
                "sub": "user-123",
                "cognito:groups": ["supervisor"],
                "custom:tenant_id": "tenant-b",
            },
            default_customer_ids=frozenset({"C001"}),
            default_tenant_id="tenant-a",
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


@pytest.mark.parametrize(
    "claims",
    [
        {"token_use": "access", "client_id": "client-id"},
        {"token_use": "id", "aud": "client-id"},
    ],
)
def test_cognito_token_use_uses_the_matching_audience_field(claims) -> None:
    assert validate_cognito_audience(claims, "client-id") == claims


def test_cognito_token_rejects_audience_mismatch() -> None:
    with pytest.raises(AuthenticationError, match="audience"):
        validate_cognito_audience(
            {"token_use": "access", "client_id": "other-client"},
            "client-id",
        )
