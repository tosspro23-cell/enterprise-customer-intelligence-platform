from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any, Callable, Mapping


class AuthenticationError(ValueError):
    """Raised when a bearer token cannot establish a trusted principal."""


AGENT_PERMISSIONS = frozenset(
    {
        "READ_CALL",
        "SUBSCRIBE_CALL",
        "INGEST_TRANSCRIPT",
        "UPDATE_COMPLAINT",
        "END_CALL",
        "RUN_POSTCALL",
    }
)
SUPERVISOR_PERMISSIONS = frozenset({"READ_CALL", "SUBSCRIBE_CALL"})


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    """Validated identity claims translated into the platform auth contract."""

    principal_id: str
    tenant_id: str
    roles: tuple[str, ...]
    permissions: frozenset[str]
    allowed_customer_ids: frozenset[str]
    purpose_of_use: str


def _claim_customer_ids(claims: Mapping[str, Any]) -> frozenset[str] | None:
    value = claims.get("custom:customer_ids")
    if value is None:
        return None
    if isinstance(value, str):
        values = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        values = value
    else:
        raise AuthenticationError("invalid customer scope claim")
    customer_ids = frozenset(str(item).strip() for item in values if str(item).strip())
    if not customer_ids:
        raise AuthenticationError("empty customer scope claim")
    return customer_ids


def principal_from_claims(
    claims: Mapping[str, Any],
    *,
    default_customer_ids: frozenset[str],
    default_tenant_id: str = "demo-tenant",
    default_purpose_of_use: str = "customer-service",
) -> AuthenticatedPrincipal:
    """Translate validated Cognito/OIDC claims into trusted application input.

    The JWT signature, issuer, audience, and expiry must be validated before
    this function is called. Customer scope is taken from an explicit custom
    claim when present; the configured default is only a synthetic-demo
    fallback and must not be used as a production tenant authorization model.
    """

    subject = str(claims.get("sub", "")).strip()
    if not subject:
        raise AuthenticationError("token has no subject")

    raw_groups = claims.get("cognito:groups", claims.get("groups", ()))
    if isinstance(raw_groups, str):
        groups = {item.strip().lower() for item in raw_groups.split(",") if item.strip()}
    elif isinstance(raw_groups, (list, tuple, set)):
        groups = {str(item).strip().lower() for item in raw_groups if str(item).strip()}
    else:
        raise AuthenticationError("invalid role claim")

    roles = tuple(role for role in ("agent", "supervisor") if role in groups)
    if not roles:
        raise AuthenticationError("token has no supported platform role")

    permissions: set[str] = set()
    if "agent" in roles:
        permissions.update(AGENT_PERMISSIONS)
    if "supervisor" in roles:
        permissions.update(SUPERVISOR_PERMISSIONS)

    customer_ids = _claim_customer_ids(claims) or default_customer_ids
    if not customer_ids:
        raise AuthenticationError("principal has no customer scope")
    return AuthenticatedPrincipal(
        principal_id=f"oidc:{subject}",
        tenant_id=str(claims.get("custom:tenant_id", default_tenant_id)),
        roles=roles,
        permissions=frozenset(permissions),
        allowed_customer_ids=customer_ids,
        purpose_of_use=str(claims.get("custom:purpose_of_use", default_purpose_of_use)),
    )


class CognitoJWTAuthenticator:
    """Validate Cognito JWTs without making identity the business authority.

    The production path uses PyJWT's JWKS client. A decoder can be injected
    for deterministic tests, keeping the core suite independent of the
    optional authentication runtime dependency.
    """

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        default_customer_ids: frozenset[str],
        default_tenant_id: str = "demo-tenant",
        default_purpose_of_use: str = "customer-service",
        decoder: Callable[[str], Mapping[str, Any]] | None = None,
        leeway_seconds: int = 5,
    ) -> None:
        if not issuer.strip() or not audience.strip():
            raise ValueError("COGNITO_ISSUER and COGNITO_AUDIENCE are required")
        self.issuer = issuer.rstrip("/")
        self.audience = audience
        self.default_customer_ids = default_customer_ids
        self.default_tenant_id = default_tenant_id
        self.default_purpose_of_use = default_purpose_of_use
        self._decoder = decoder or self._build_decoder(leeway_seconds)

    def _build_decoder(self, leeway_seconds: int) -> Callable[[str], Mapping[str, Any]]:
        try:
            jwt = import_module("jwt")
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Cognito authentication requires the auth-runtime dependency"
            ) from exc

        jwks_client = jwt.PyJWKClient(
            f"{self.issuer}/.well-known/jwks.json",
            cache_jwk_set=True,
            lifespan=300,
        )

        def decode(token: str) -> Mapping[str, Any]:
            signing_key = jwks_client.get_signing_key_from_jwt(token)
            return jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
                leeway=leeway_seconds,
                options={"require": ["exp", "iat", "sub"]},
            )

        return decode

    def authenticate(self, token: str) -> AuthenticatedPrincipal:
        if not token or any(character.isspace() for character in token):
            raise AuthenticationError("invalid bearer token")
        try:
            claims = self._decoder(token)
            return principal_from_claims(
                claims,
                default_customer_ids=self.default_customer_ids,
                default_tenant_id=self.default_tenant_id,
                default_purpose_of_use=self.default_purpose_of_use,
            )
        except AuthenticationError:
            raise
        except Exception as exc:
            # Do not expose JWT, network, or key-set details to the caller.
            raise AuthenticationError("invalid bearer token") from exc
