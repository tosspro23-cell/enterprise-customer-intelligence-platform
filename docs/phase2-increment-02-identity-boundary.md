# Phase Two increment 02: identity boundary and request budget

Status: implementation PR; the current AWS demo remains in `AUTH_MODE=demo`.

## Decision

Add an explicit, opt-in Cognito/OIDC JWT boundary to the FastAPI application and
an in-process request budget for defense in depth. Keep the existing demo
principal path as the default so local/reference behavior and the current
synthetic cloud canary remain reversible.

The boundary translates validated identity claims into the existing
`AuthContext`. It does not let a token, a model response, or a browser header
become business authority. The existing permission, tenant, customer-scope,
revision, and publication checks remain authoritative.

## Authentication contract

`AUTH_MODE=demo` preserves the local `X-Principal-ID` behavior. This mode is
synthetic-only and is not an enterprise identity mechanism.

`AUTH_MODE=cognito` requires:

- `Authorization: Bearer <JWT>` on every protected API request;
- `COGNITO_ISSUER` and `COGNITO_AUDIENCE` configuration;
- signature validation against the issuer JWKS, with issuer, token use,
  audience/client ID, expiry, and required subject/issued-at claims checked;
- an `agent` or `supervisor` group claim;
- an explicit customer scope claim (`custom:customer_ids`) when the identity
  provider has one. `AUTH_CUSTOMER_IDS` is only a synthetic fallback and is not
  a production tenant authorization design;
- a tenant claim, when present, that matches the single configured tenant. The
  current SQLite schema does not support cross-tenant history, so a different
  tenant claim is rejected rather than being treated as isolated data;
- concrete `CORS_ALLOWED_ORIGINS`; wildcard CORS is rejected in this mode.

Health remains unauthenticated for a load balancer or operator probe. Scenario
catalog and business APIs require the configured auth mode. Invalid or missing
bearer tokens return `401` without exposing key-set or decoder details.

## Request budget

The application applies `RATE_LIMIT_REQUESTS_PER_MINUTE` (default `120`) to
API traffic per client address, excluding health and CORS preflight requests.
It returns `429` with `Retry-After` when the budget is exhausted.

This is deliberately a bounded single-process control. It is not a substitute
for an API Gateway, ALB/WAF, or a shared distributed limiter and must not be
used as the consistency boundary after horizontal scaling.

## Acceptance evidence

- claims map to roles, permissions, tenant, customer scope, and purpose of use;
- unsupported roles, empty scopes, missing bearer tokens, invalid JWTs, and
  decoder failures are rejected without leaking token-validation details;
- demo mode remains compatible with the existing Workbench;
- the request budget expires, returns a retry interval, bounds key cardinality,
  and protects API traffic while excluding health;
- the SSM update contract validates auth-mode configuration and passes the
  explicit runtime settings to the container;
- the deterministic suite, shell contract tests, and container path remain
  green.

## Cloud boundary and non-goals

This increment does not enable Cognito on the current HTTP Elastic-IP endpoint,
create a public user pool, or claim HTTPS. Enabling real identity on that
endpoint would leave transport and browser token acquisition unresolved. The
next cloud increment must choose and verify one edge path (for example, an AWS
managed HTTPS endpoint or ALB plus ACM), then wire a tested login/token flow
and keep the direct host path restricted or removed.

It also does not introduce PostgreSQL, cross-process coordination, Fargate,
WAF, or real customer data. SQLite and process-local live state remain the
current single-host boundary.
