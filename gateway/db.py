"""asyncpg pool to the gateway schema (Supabase 'MCP' project Postgres)."""
import asyncpg

from .config import settings

_pool: asyncpg.Pool | None = None


async def pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        url = settings().database_url
        if not url:
            raise RuntimeError("DATABASE_URL is not configured")
        _pool = await asyncpg.create_pool(url, min_size=1, max_size=8, command_timeout=30)
    return _pool


async def close() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def set_pool_for_tests(p) -> None:
    global _pool
    _pool = p
