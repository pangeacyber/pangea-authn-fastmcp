from __future__ import annotations

from typing import Protocol, TypeVar

KeyT = TypeVar("KeyT", bound=str, contravariant=True)
ValueT = TypeVar("ValueT")


class Repository(Protocol[KeyT, ValueT]):
    """An asynchronous key-value store."""

    async def get(self, key: KeyT) -> ValueT | None: ...

    async def set(self, key: KeyT, value: ValueT) -> None: ...

    async def delete(self, key: KeyT) -> None: ...
