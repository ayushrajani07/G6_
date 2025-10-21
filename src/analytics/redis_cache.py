"""
Redis Cache for G6 Platform
Real-time data caching with fallback handling.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from src.error_handling import handle_api_error

# Central time helpers (UTC aware)
try:
    from src.utils.timeutils import ensure_utc_helpers  # type: ignore
    _utc_now, _isoformat_z = ensure_utc_helpers()
    def utc_now():  # type: ignore
        return _utc_now()
    def isoformat_z(ts):  # type: ignore
        try:
            return _isoformat_z(ts)
        except Exception:
            return str(ts)
except Exception:  # fallback if utilities unavailable early
    from datetime import datetime
    def utc_now():  # type: ignore
        return datetime.now(UTC)
    def isoformat_z(ts):  # type: ignore
        try:
            return ts.isoformat().replace('+00:00','Z')
        except Exception:
            return str(ts)

try:
    import redis as _redis  # type: ignore
    redis = _redis  # ensure name bound for type checkers
    REDIS_AVAILABLE = True
except ImportError:  # pragma: no cover
    redis = None  # type: ignore[assignment]
    REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)

class RedisCache:
    """
    Redis cache implementation for G6 real-time data.
    Handles connection failures gracefully with local fallback.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: str | None = None,
        socket_timeout: float = 5.0,
        connection_pool_max_connections: int = 10,
        decode_responses: bool = True,
        fallback_to_memory: bool = True
    ):
        """Initialize Redis cache with fallback support."""

        self.fallback_to_memory = fallback_to_memory
        self._memory_cache: dict[str, Any] = {}
        self._redis_available = False
        self._client = None  # type: ignore[assignment]

        if not REDIS_AVAILABLE:
            logger.warning("Redis not available, using memory fallback")
            return

        try:
            pool = redis.ConnectionPool(  # type: ignore[union-attr]
                host=host,
                port=port,
                db=db,
                password=password,
                socket_timeout=socket_timeout,
                max_connections=connection_pool_max_connections,
                decode_responses=decode_responses
            )

            self._client = redis.Redis(connection_pool=pool)  # type: ignore[union-attr]

            # Test connection
            self._client.ping()
            self._redis_available = True
            logger.info(f"Redis cache connected: {host}:{port}")

        except Exception as e:
            handle_api_error(e, component="analytics.redis_cache", context={"stage": "connect"})
            logger.warning(f"Redis connection failed: {e}, using fallback")
            if not self.fallback_to_memory:
                raise

    def _serialize(self, value: Any) -> str:
        """Serialize value for storage."""
        if isinstance(value, (str, int, float, bool)):
            return json.dumps(value)
        elif isinstance(value, datetime):
            return json.dumps(value.isoformat())
        else:
            return json.dumps(value, default=str)

    def _deserialize(self, value: str) -> Any:
        """Deserialize value from storage."""
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """Set cache value with optional TTL."""
        try:
            if self._redis_available and self._client:
                serialized = self._serialize(value)
                result = self._client.set(key, serialized, ex=ttl)
                return bool(result)
            elif self.fallback_to_memory:
                self._memory_cache[key] = {
                    'value': value,
                    'expires': utc_now() + timedelta(seconds=ttl) if ttl else None
                }
                return True
            return False

        except Exception as e:
            handle_api_error(e, component="analytics.redis_cache", context={"op": "set", "key": key})
            logger.warning(f"Cache set failed for {key}: {e}")
            if self.fallback_to_memory:
                self._memory_cache[key] = {'value': value, 'expires': None}
                return True
            return False

    def get(self, key: str) -> Any:
        """Get cache value."""
        try:
            if self._redis_available and self._client:
                value = self._client.get(key)
                value_str = cast(str | None, value) if value is not None else None
                return self._deserialize(value_str) if value_str else None
            elif self.fallback_to_memory:
                cached = self._memory_cache.get(key)
                if cached:
                    if cached['expires'] and utc_now() > cached['expires']:
                        del self._memory_cache[key]
                        return None
                    return cached['value']
                return None
            return None

        except Exception as e:
            handle_api_error(e, component="analytics.redis_cache", context={"op": "get", "key": key})
            logger.warning(f"Cache get failed for {key}: {e}")
            return None

    def delete(self, key: str) -> bool:
        """Delete cache key."""
        try:
            if self._redis_available and self._client:
                result = self._client.delete(key)
                return bool(result)
            elif self.fallback_to_memory:
                if key in self._memory_cache:
                    del self._memory_cache[key]
                    return True
                return False
            return False

        except Exception as e:
            handle_api_error(e, component="analytics.redis_cache", context={"op": "delete", "key": key})
            logger.warning(f"Cache delete failed for {key}: {e}")
            return False

    def exists(self, key: str) -> bool:
        """Check if key exists."""
        try:
            if self._redis_available and self._client:
                return bool(self._client.exists(key))
            elif self.fallback_to_memory:
                cached = self._memory_cache.get(key)
                if cached and cached['expires'] and utc_now() > cached['expires']:
                    del self._memory_cache[key]
                    return False
                return key in self._memory_cache
            return False

        except Exception as e:
            handle_api_error(e, component="analytics.redis_cache", context={"op": "exists", "key": key})
            logger.warning(f"Cache exists check failed for {key}: {e}")
            return False

    def set_metric(self, metric_key: str, data: dict[str, Any], ttl: int = 300) -> bool:
        """Set metric data with default 5-minute TTL."""
        key = f"g6:metrics:{metric_key}"
        return self.set(key, data, ttl)

    def get_metric(self, metric_key: str) -> dict[str, Any] | None:
        """Get metric data."""
        key = f"g6:metrics:{metric_key}"
        return self.get(key)

    def set_overview_snapshot(self, index: str, data: dict[str, Any], ttl: int = 60) -> bool:
        """Set overview snapshot with 1-minute TTL."""
        key = f"g6:overview:{index}"
        return self.set(key, data, ttl)

    def get_overview_snapshot(self, index: str) -> dict[str, Any] | None:
        """Get overview snapshot."""
        key = f"g6:overview:{index}"
        return self.get(key)

    def set_options_chain(self, index: str, expiry: str, data: dict[str, Any], ttl: int = 30) -> bool:
        """Set options chain with 30-second TTL."""
        key = f"g6:options:{index}:{expiry}"
        return self.set(key, data, ttl)

    def get_options_chain(self, index: str, expiry: str) -> dict[str, Any] | None:
        """Get options chain."""
        key = f"g6:options:{index}:{expiry}"
        return self.get(key)

    def flush_all(self) -> bool:
        """Flush all cache data."""
        try:
            if self._redis_available and self._client:
                self._client.flushdb()
                return True
            elif self.fallback_to_memory:
                self._memory_cache.clear()
                return True
            return False

        except Exception as e:
            handle_api_error(e, component="analytics.redis_cache", context={"op": "flush_all"})
            logger.warning(f"Cache flush failed: {e}")
            return False

    def get_info(self) -> dict[str, Any]:
        """Get cache information."""
        try:
            if self._redis_available and self._client:
                info = self._client.info()
                info_dict = cast(dict[str, Any], info)
                return {
                    "type": "redis",
                    "connected": True,
                    "memory_usage": info_dict.get("used_memory_human", "unknown"),
                    "connected_clients": info_dict.get("connected_clients", 0),
                    "total_commands_processed": info_dict.get("total_commands_processed", 0)
                }
            elif self.fallback_to_memory:
                return {
                    "type": "memory_fallback",
                    "connected": True,
                    "keys_count": len(self._memory_cache),
                    "memory_usage": f"{len(str(self._memory_cache))} chars"
                }
            else:
                return {
                    "type": "disabled",
                    "connected": False
                }

        except Exception as e:
            handle_api_error(e, component="analytics.redis_cache", context={"op": "get_info"})
            logger.warning(f"Failed to get cache info: {e}")
            return {"type": "error", "connected": False, "error": str(e)}

    def health_check(self) -> bool:
        """Check cache health."""
        try:
            test_key = "g6:health_check"
            test_value = {"timestamp": isoformat_z(utc_now())}

            if self.set(test_key, test_value, 10):
                retrieved = self.get(test_key)
                self.delete(test_key)
                return retrieved == test_value
            return False

        except Exception as e:
            handle_api_error(e, component="analytics.redis_cache", context={"op": "health_check"})
            logger.warning(f"Cache health check failed: {e}")
            return False
