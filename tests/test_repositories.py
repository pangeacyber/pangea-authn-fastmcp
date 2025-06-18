from __future__ import annotations

import pytest

from pangea_authn_fastmcp import InMemoryRepository


@pytest.fixture(scope="module")
def in_memory_repository() -> InMemoryRepository[str, str]:
    return InMemoryRepository()


async def test_in_memory(in_memory_repository: InMemoryRepository[str, str]) -> None:
    assert await in_memory_repository.get("foo") is None

    await in_memory_repository.set("foo", "bar")
    assert await in_memory_repository.get("foo") == "bar"

    await in_memory_repository.delete("foo")
    assert await in_memory_repository.get("foo") is None
