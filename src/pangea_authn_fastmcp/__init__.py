from __future__ import annotations

from importlib.metadata import version

from pangea_authn_fastmcp.oauth_provider import PangeaOAuthProvider
from pangea_authn_fastmcp.repositories.in_memory_repository import InMemoryRepository
from pangea_authn_fastmcp.repositories.pangea_vault_repository import PangeaVaultRepository
from pangea_authn_fastmcp.repositories.repository import Repository

__version__ = version(__package__)

__all__ = ("PangeaOAuthProvider", "InMemoryRepository", "PangeaVaultRepository", "Repository")
