from __future__ import annotations

from fastmcp import FastMCP
from mcp.server.auth.settings import ClientRegistrationOptions

from pangea_authn_fastmcp import PangeaOAuthProvider

PANGEA_AUTHN_ISSUER_URL = "https://pdn-placeholder.login.aws.us.pangea.cloud"
PANGEA_AUTHN_CLIENT_ID = "psa_[...]"
PANGEA_AUTHN_CLIENT_SECRET = "pck_[...]"
PANGEA_VAULT_TOKEN = "pts_[...]"

MCP_SCOPES = ["user"]

MCP_ISSUER_URL = "http://localhost:8000"


def test_foo() -> None:
    oauth_provider = PangeaOAuthProvider(
        mcp_issuer_url=MCP_ISSUER_URL,
        pangea_authn_issuer_url=PANGEA_AUTHN_ISSUER_URL,
        pangea_authn_client_id=PANGEA_AUTHN_CLIENT_ID,
        pangea_authn_client_secret=PANGEA_AUTHN_CLIENT_SECRET,
        mcp_scopes=MCP_SCOPES,
        pangea_authn_scopes=MCP_SCOPES,
        client_registration_options=ClientRegistrationOptions(
            enabled=True, valid_scopes=MCP_SCOPES, default_scopes=MCP_SCOPES
        ),
        required_scopes=MCP_SCOPES,
    )

    mcp: FastMCP[None] = FastMCP(auth=oauth_provider)

    mcp.custom_route("/pangea/callback", methods=["GET"])(oauth_provider.callback_handler)

    assert isinstance(mcp.auth, PangeaOAuthProvider)
