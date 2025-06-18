from __future__ import annotations

from typing import override

from pangea.asyncio.services.vault import VaultAsync
from pangea.services.vault.models.common import ItemType, Secret
from pydantic import BaseModel
from typing_extensions import TypeVar

from pangea_authn_fastmcp.repositories.repository import Repository

ValueT = TypeVar("ValueT", bound=BaseModel)


class PangeaVaultRepository(Repository[str, ValueT]):
    """A key-value store that's backed by Pangea Vault."""

    _value_type: type[ValueT]
    _client: VaultAsync

    def __init__(self, value_type: type[ValueT], pangea_vault_token: str) -> None:
        """
        A key-value store that's backed by Pangea Vault.

        Args:
            value_type: Value type associated with this repository.
            pangea_vault_token: Pangea Vault API token.
        """

        self._value_type = value_type
        self._client = VaultAsync(token=pangea_vault_token)

    @override
    async def get(self, key: str) -> ValueT | None:
        existing = await self._get_vault_secret(key)

        if not existing:
            return None

        if not existing.item_versions[-1].secret:
            return None

        return self._value_type.model_validate_json(existing.item_versions[-1].secret)

    @override
    async def set(self, key: str, value: ValueT) -> None:
        existing = await self._get_vault_secret(key)

        if existing:
            await self._client.rotate_secret(existing.id, value.model_dump_json())
        else:
            await self._client.store_secret(value.model_dump_json(), name=key)

    @override
    async def delete(self, key: str) -> None:
        existing = await self._get_vault_secret(key)

        if not existing:
            return None

        await self._client.delete(existing.id)

    async def _get_vault_secret(self, key: str) -> Secret | None:
        response = await self._client.get_bulk({"type": ItemType.SECRET, "name": key}, size=1)

        if not response.result:
            return None

        if len(response.result.items) == 0:
            return None

        item = response.result.items[0]
        assert item.type == ItemType.SECRET
        return item
