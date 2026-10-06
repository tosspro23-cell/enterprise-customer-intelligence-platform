from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4

from .models import AuthContext, CallBinding


class AuthorizationError(PermissionError):
    """Raised when trusted authorization does not permit an operation."""


class AuthorizationRegistry:
    """Small versioned identity registry used by the reference implementation."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._contexts: dict[str, AuthContext] = {}

    def register(
        self,
        principal_id: str,
        *,
        permissions: set[str],
        allowed_customer_ids: set[str],
        roles: tuple[str, ...] = ("agent",),
        tenant_id: str = "demo-tenant",
        purpose_of_use: str = "customer-service",
    ) -> AuthContext:
        with self._lock:
            current = self._contexts.get(principal_id)
            version = (current.authz_version + 1) if current else 1
            context = AuthContext(
                principal_id=principal_id,
                tenant_id=tenant_id,
                roles=roles,
                permissions=frozenset(permissions),
                allowed_customer_ids=frozenset(allowed_customer_ids),
                purpose_of_use=purpose_of_use,
                correlation_id=str(uuid4()),
                authz_version=version,
                issued_at=datetime.now(timezone.utc),
            )
            self._contexts[principal_id] = context
            return context

    def get(self, principal_id: str) -> AuthContext:
        with self._lock:
            if principal_id not in self._contexts:
                raise AuthorizationError(f"unknown principal: {principal_id}")
            return self._contexts[principal_id]

    def revoke(self, principal_id: str, *permissions: str) -> AuthContext:
        with self._lock:
            current = self.get(principal_id)
            remaining = set(current.permissions).difference(permissions)
            return self.register(
                principal_id,
                permissions=remaining,
                allowed_customer_ids=set(current.allowed_customer_ids),
                roles=current.roles,
                tenant_id=current.tenant_id,
                purpose_of_use=current.purpose_of_use,
            )

    def grant(self, principal_id: str, *permissions: str) -> AuthContext:
        with self._lock:
            current = self.get(principal_id)
            return self.register(
                principal_id,
                permissions=set(current.permissions).union(permissions),
                allowed_customer_ids=set(current.allowed_customer_ids),
                roles=current.roles,
                tenant_id=current.tenant_id,
                purpose_of_use=current.purpose_of_use,
            )

    def check(
        self,
        supplied: AuthContext,
        *,
        permission: str,
        binding: CallBinding,
        require_current_version: bool = True,
    ) -> None:
        current = self.get(supplied.principal_id)
        if require_current_version and current.authz_version != supplied.authz_version:
            raise AuthorizationError("authorization context is stale")
        if permission not in current.permissions:
            raise AuthorizationError(f"permission denied: {permission}")
        if supplied.tenant_id != binding.tenant_id or current.tenant_id != binding.tenant_id:
            raise AuthorizationError("tenant scope mismatch")
        if binding.customer_id not in current.allowed_customer_ids:
            raise AuthorizationError("customer is outside the trusted authorization scope")

    def current_for(self, principal_id: str, correlation_id: str | None = None) -> AuthContext:
        current = self.get(principal_id)
        if correlation_id is None:
            return current
        return replace(current, correlation_id=correlation_id)
