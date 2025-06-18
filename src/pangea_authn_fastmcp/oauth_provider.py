from __future__ import annotations

import time
from base64 import b64encode
from hashlib import sha256
from secrets import token_hex, token_urlsafe
from typing import TYPE_CHECKING, override

import httpx
from fastmcp.server.auth.auth import OAuthProvider
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyHttpUrl, AnyUrl
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse, RedirectResponse, Response

from pangea_authn_fastmcp.repositories.in_memory_repository import InMemoryRepository

if TYPE_CHECKING:
    from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
    from starlette.requests import Request

    from pangea_authn_fastmcp.repositories.repository import Repository


AUTHORIZATION_PATH = "/v2/oauth/authorize"
TOKEN_PATH = "/v2/oauth/token"
REGISTRATION_PATH = "/v2/oauth/clients/register"

DEFAULT_ACCESS_TOKEN_EXPIRY_SECONDS = 60 * 60  # 1 hour.


def sri_hash(x: str) -> str:
    return f"sha256-{b64encode(sha256(x.encode('utf-8')).digest()).decode('utf-8')}"


class PangeaOAuthProvider(OAuthProvider):
    """An OAuth provider that defers to Pangea AuthN for authentication."""

    def __init__(
        self,
        *,
        mcp_issuer_url: AnyHttpUrl | str,
        mcp_scopes: list[str],
        pangea_authn_issuer_url: AnyHttpUrl | str,
        pangea_authn_client_id: str,
        pangea_authn_client_secret: str,
        pangea_authn_scopes: list[str],
        # Repositories.
        access_tokens_repository: Repository[str, AccessToken] = InMemoryRepository(),
        auth_codes_repository: Repository[str, AuthorizationCode] = InMemoryRepository(),
        clients_repository: Repository[str, OAuthClientInformationFull] = InMemoryRepository(),
        # OAuthProvider kwargs.
        service_documentation_url: AnyHttpUrl | str | None = None,
        client_registration_options: ClientRegistrationOptions | None = None,
        revocation_options: RevocationOptions | None = None,
        required_scopes: list[str] | None = None,
    ) -> None:
        """
        An OAuth provider that defers to Pangea AuthN for authentication.

        Args:
            mcp_issuer_url: URL of the MCP server.
            mcp_scopes: Scopes that are available to the MCP server.
            pangea_authn_issuer_url: Issuer URL of the Pangea AuthN project.
            pangea_authn_client_id: Pangea AuthN OAuth client ID.
            pangea_authn_client_secret: Pangea AuthN OAuth client secret.
            pangea_authn_scopes: Scopes that are available to the Pangea AuthN project.
            access_tokens_repository: Repository for storing access tokens.
            auth_codes_repository: Repository for storing authorization codes.
            clients_repository: Repository for storing OAuth clients.
            service_documentation_url: URL of the service documentation.
            client_registration_options: Client registration options.
            revocation_options: Revocation options.
            required_scopes: Scopes that are required for all requests.
        """

        super().__init__(
            issuer_url=mcp_issuer_url,
            service_documentation_url=service_documentation_url,
            client_registration_options=client_registration_options,
            revocation_options=revocation_options,
            required_scopes=required_scopes,
        )

        self.mcp_issuer_url = mcp_issuer_url
        self.mcp_scopes = mcp_scopes
        self.pangea_issuer_url = pangea_authn_issuer_url
        self.client_id = pangea_authn_client_id
        self.client_secret = pangea_authn_client_secret
        self.pangea_authn_scopes = pangea_authn_scopes

        self.authorize_url = AnyHttpUrl(str(self.pangea_issuer_url).rstrip("/") + AUTHORIZATION_PATH)
        self.token_url = AnyHttpUrl(str(self.pangea_issuer_url).rstrip("/") + TOKEN_PATH)
        self.registration_endpoint = AnyHttpUrl(str(self.pangea_issuer_url).rstrip("/") + REGISTRATION_PATH)

        self.access_tokens = access_tokens_repository
        self.auth_codes = auth_codes_repository
        self.clients = clients_repository

        self.state_mapping: dict[str, dict[str, str]] = {}

    @override
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        """Retrieve an OAuth client by its ID."""

        return await self.clients.get(client_id)

    @override
    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        """Register a new OAuth client."""

        await self.clients.set(client_info.client_id, client_info)

    @override
    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        """Generate an authorization URL for the Pangea AuthN OAuth flow."""

        if not await self.clients.get(client.client_id):
            raise AuthorizeError(
                error="unauthorized_client", error_description=f"Client '{client.client_id}' not registered."
            )

        state = params.state or token_urlsafe(32)

        self.state_mapping[state] = {
            "client_id": client.client_id,
            "code_challenge": params.code_challenge,
            "redirect_uri_provided_explicitly": str(params.redirect_uri_provided_explicitly),
            "redirect_uri": str(params.redirect_uri),
        }

        return construct_redirect_uri(
            str(self.authorize_url),
            client_id=self.client_id,
            redirect_uri=str(self.mcp_issuer_url).rstrip("/") + "/pangea/callback",
            response_type="code",
            state=state,
            scope=" ".join(params.scopes or self.pangea_authn_scopes),
        )

    @override
    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        """Retrieve an authorization code."""

        auth_code = await self.auth_codes.get(authorization_code)

        if not auth_code:
            return None

        # Belongs to a different client.
        if auth_code.client_id != client.client_id:
            return None

        # Expired.
        if auth_code.expires_at < time.time():
            await self.auth_codes.delete(authorization_code)
            return None

        return auth_code

    @override
    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        """Exchange an authorization code for a token."""

        if not await self.auth_codes.get(authorization_code.code):
            raise TokenError("invalid_grant", "Authorization code not found or already used.")

        # Consume the authorization code.
        await self.auth_codes.delete(authorization_code.code)

        mcp_token = f"mcp_{token_hex(32)}"

        await self.access_tokens.set(
            sri_hash(mcp_token),
            AccessToken(
                token=mcp_token,
                client_id=client.client_id,
                scopes=authorization_code.scopes,
                expires_at=int(time.time() + DEFAULT_ACCESS_TOKEN_EXPIRY_SECONDS),
            ),
        )

        return OAuthToken(
            access_token=mcp_token,
            token_type="Bearer",
            expires_in=DEFAULT_ACCESS_TOKEN_EXPIRY_SECONDS,
            scope=" ".join(authorization_code.scopes),
        )

    @override
    async def load_access_token(self, token: str) -> AccessToken | None:
        """Load and validate an access token."""

        access_token = await self.access_tokens.get(sri_hash(token))
        if not access_token:
            return None

        if access_token.expires_at and access_token.expires_at < time.time():
            await self.access_tokens.delete(sri_hash(token))
            return None

        return access_token

    @override
    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        """Revoke a token."""

        if isinstance(token, AccessToken):
            await self.access_tokens.delete(sri_hash(token.token))
        elif isinstance(token, RefreshToken):
            raise NotImplementedError()

    @override
    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        raise NotImplementedError()

    @override
    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> OAuthToken:
        raise NotImplementedError()

    async def callback_handler(self, request: Request) -> Response:
        """Callback handler that can be passed to FastMCP's `custom_route`."""

        code = request.query_params.get("code")
        state = request.query_params.get("state")

        if not code or not state:
            raise HTTPException(400, "Missing code or state parameter")

        try:
            redirect_uri = await self._handle_pangea_callback(code, state)
            return RedirectResponse(status_code=302, url=redirect_uri)
        except Exception:
            return JSONResponse(
                status_code=500,
                content={
                    "error": "server_error",
                    "error_description": "Unexpected error",
                },
            )

    async def _handle_pangea_callback(self, code: str, state: str) -> str:
        """Handle Pangea AuthN OAuth callback."""

        state_data = self.state_mapping.get(state)
        if not state_data:
            raise HTTPException(400, "Invalid state parameter")

        redirect_uri = state_data["redirect_uri"]
        code_challenge = state_data["code_challenge"]
        redirect_uri_provided_explicitly = state_data["redirect_uri_provided_explicitly"] == "True"
        client_id = state_data["client_id"]

        # Exchange code for token with Pangea AuthN.
        async with httpx.AsyncClient() as client:
            response = await client.post(
                str(self.token_url),
                data={
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": f"{self.mcp_issuer_url}/pangea/callback",
                },
                headers={"Accept": "application/json"},
                auth=httpx.BasicAuth(username=self.client_id, password=self.client_secret),
            )

            if response.status_code != 200:
                raise HTTPException(400, "Failed to exchange code for token")

            data = response.json()

            if "error" in data:
                raise HTTPException(400, data.get("error_description", data["error"]))

            pangea_token = data["access_token"]

            # Create MCP authorization code.
            mcp_auth_code = f"mcp_{token_hex(16)}"
            auth_code = AuthorizationCode(
                code=mcp_auth_code,
                client_id=client_id,
                # Note this must be an `AnyUrl`, not an `AnyHttpUrl`, in order
                # to satisfy an equality check in the MCP SDK.
                redirect_uri=AnyUrl(redirect_uri),
                redirect_uri_provided_explicitly=redirect_uri_provided_explicitly,
                expires_at=time.time() + 300,
                scopes=self.mcp_scopes,
                code_challenge=code_challenge,
            )
            await self.auth_codes.set(mcp_auth_code, auth_code)

            # Store Pangea token; the MCP token will be mapped to this later
            await self.access_tokens.set(
                sri_hash(pangea_token),
                AccessToken(
                    token=pangea_token,
                    client_id=client_id,
                    scopes=[],
                    expires_at=None,
                ),
            )

        del self.state_mapping[state]
        return construct_redirect_uri(redirect_uri, code=mcp_auth_code, state=state)
