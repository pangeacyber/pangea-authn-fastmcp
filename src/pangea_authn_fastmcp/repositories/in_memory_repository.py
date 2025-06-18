from __future__ import annotations

from typing import override

from pangea_authn_fastmcp.repositories.repository import KeyT, Repository, ValueT


class InMemoryRepository(Repository[KeyT, ValueT]):
    """An in-memory key-value store."""

    _data: dict[KeyT, ValueT] = {}

    @override
    async def get(self, key: KeyT) -> ValueT | None:
        return self._data.get(key)

    @override
    async def set(self, key: KeyT, value: ValueT) -> None:
        self._data[key] = value

    @override
    async def delete(self, key: KeyT) -> None:
        del self._data[key]
