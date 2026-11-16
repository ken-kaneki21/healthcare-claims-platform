"""Validate signed access tokens against a configured OIDC issuer."""

from urllib.parse import urlsplit


class OidcIdentity:
    def __init__(
        self, issuer: str, audience: str, jwks_url: str, role: str | None = None
    ):
        import jwt

        for address in (issuer, jwks_url):
            parsed = urlsplit(address)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.fragment
                or parsed.query
            ):
                raise ValueError("OIDC issuer and JWKS must be HTTPS URLs")
        if not audience:
            raise ValueError("OIDC audience is required")
        self.issuer = issuer
        self.audience = audience
        self.role = role
        self.keys = jwt.PyJWKClient(jwks_url, lifespan=300, timeout=3)

    def __call__(self, token: str) -> int:
        import jwt

        if not 0 < len(token) <= 8192:
            raise ValueError("Invalid access token size")
        try:
            header = jwt.get_unverified_header(token)
            token_type = header.get("typ")
            if (
                header.get("alg") != "RS256"
                or not isinstance(token_type, str)
                or token_type.lower()
                not in (
                    "at+jwt",
                    "application/at+jwt",
                )
            ):
                raise ValueError("Expected a signed JWT access token")
            key = self.keys.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
                options={
                    "require": ["exp", "iat", "iss", "aud", "sub", "tenant_id", "scope"]
                },
            )
        except jwt.PyJWTError as error:
            raise ValueError("Invalid access token") from error
        tenant = claims["tenant_id"]
        scope = claims["scope"]
        realm_access = claims.get("realm_access")
        roles = realm_access.get("roles") if isinstance(realm_access, dict) else None
        if (
            type(tenant) is not int
            or tenant not in (1, 2, 3)
            or not isinstance(scope, str)
            or "claims:read" not in scope.split()
            or (
                self.role is not None
                and (not isinstance(roles, list) or self.role not in roles)
            )
        ):
            raise ValueError("Access token lacks claims authorization")
        return tenant
