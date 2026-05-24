"""
Distributed Database Manager - Enterprise Storage Abstraction Layer
================================================================

PostgreSQL + Redis + SQLite vector + Object Storage Abstraction
- Async connection pooling
- Read/write separation
- Event partitioning
- Distributed locks
- WAL optimization
- Multi-node support

Architecture:
- PostgreSQL: Primary transactional DB
- Redis Streams: Event queues, caching, locks
- SQLite vector: Vector embeddings
- Object Storage: Attachments
"""
from __future__ import annotations  # defer type-hint evaluation; MigrationEngine is not yet implemented

import asyncio
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

# PostgreSQL async driver
try:
    import asyncpg
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False

# Redis async driver — the modern redis-py async API replaces the deprecated
# standalone aioredis package.
try:
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

# SQLite vector storage is implemented locally in this lightweight build.
SQLITE_VECTOR_AVAILABLE = True

logger = logging.getLogger("distributed.db")


class DatabaseType(Enum):
    POSTGRESQL = "postgresql"
    REDIS = "redis"
    SQLITE_VECTOR = "sqlite_vector"
    OBJECT_STORAGE = "object_storage"
    SQLITE = "sqlite"


class TransactionIsolation(Enum):
    READ_COMMITTED = "READ COMMITTED"
    REPEATABLE_READ = "REPEATABLE READ"
    SERIALIZABLE = "SERIALIZABLE"


@dataclass
class DatabaseConfig:
    """Database configuration"""
    db_type: DatabaseType
    host: str = "localhost"
    port: int = 5432
    username: str = "postgres"
    password: str = ""
    database: str = "aiemailorganizer"
    pool_size: int = 20
    min_pool_size: int = 5
    max_pool_size: int = 50
    pool_timeout: int = 30
    command_timeout: int = 60
    use_ssl: bool = True
    ssl_cert_path: Optional[str] = None
    ssl_key_path: Optional[str] = None

    # Connection string alias
    @property
    def connection_string(self) -> str:
        """Generate connection string"""
        if self.db_type == DatabaseType.POSTGRESQL:
            return f"postgresql+asyncpg://{self.username}:{self.password}@{self.host}:{self.port}/{self.database}"
        elif self.db_type == DatabaseType.REDIS:
            return f"redis://:{self.password}@{self.host}:{self.port}"
        return ""


@dataclass
class QueryResult:
    """Query execution result"""
    rows: List[Dict[str, Any]]
    row_count: int
    last_oid: Optional[int]
    execution_time_ms: float


@dataclass
class MigrationState:
    """Migration state tracking"""
    version: int
    description: str
    applied_at: float
    checksum: str
    rollback_sql: Optional[str] = None


class DatabaseError(Exception):
    """General database error"""
    pass


class ConnectionError(DatabaseError):
    """Connection error"""
    pass


class PoolExhaustedError(DatabaseError):
    """Pool exhausted error"""
    pass


class QueryError(DatabaseError):
    """Query execution error"""
    pass


# =============================================================================
# PostgreSQL Manager
# =============================================================================

class PostgresConnectionPool:
    """
    Enterprise PostgreSQL async connection pool.
    Supports read/write separation, connection pooling, and failover.
    """

    def __init__(self, config: DatabaseConfig):
        self.config = config
        self._pool: Optional[asyncpg.Pool] = None
        self._read_pool: Optional[asyncpg.Pool] = None
        self._lock = asyncio.Lock()
        self._health_check_task: Optional[asyncio.Task] = None
        self._is_healthy = False

        # Metrics
        self._query_count = 0
        self._error_count = 0
        self._total_query_time = 0.0

    async def initialize(self):
        """Initialize connection pool"""
        async with self._lock:
            if self._pool is not None:
                return

            if not POSTGRES_AVAILABLE:
                raise DatabaseError("asyncpg not installed")

            # Create connection pool
            self._pool = await asyncpg.create_pool(
                host=self.config.host,
                port=self.config.port,
                user=self.config.username,
                password=self.config.password,
                database=self.config.database,
                min_size=self.config.min_pool_size,
                max_size=self.config.pool_size,
                command_timeout=self.config.command_timeout,
                timeout=self.config.pool_timeout,
            )

            # Create read replica pool if configured
            read_host = os.environ.get("POSTGRES_READ_HOST")
            if read_host:
                self._read_pool = await asyncpg.create_pool(
                    host=read_host,
                    port=self.config.port,
                    user=self.config.username,
                    password=self.config.password,
                    database=self.config.database,
                    min_size=2,
                    max_size=10,
                )

            self._is_healthy = True

            # Start health check
            self._health_check_task = asyncio.create_task(self._health_check())

            logger.info(f"PostgreSQL pool initialized: {self.config.host}:{self.config.port}")

    async def _handle_pool_exception(self, exc: Exception):
        """Handle pool exception"""
        logger.error(f"Pool exception: {exc}")
        self._error_count += 1

    async def health_check(self) -> bool:
        """Verify pool health"""
        if not self._pool:
            return False

        try:
            async with self._pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            self._is_healthy = False
            return False

    async def _health_check(self):
        """Periodic health check"""
        while True:
            try:
                await asyncio.sleep(30)
                await self.health_check()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health check error: {e}")

    @asynccontextmanager
    async def connection(self, read_only: bool = False):
        """Acquire connection from pool"""
        pool = self._read_pool if read_only and self._read_pool else self._pool

        if not pool:
            raise ConnectionError("Pool not initialized")

        try:
            async with pool.acquire() as conn:
                yield conn
        except asyncpg.PostgresConnectionError as e:
            self._error_count += 1
            raise ConnectionError(f"Connection failed: {e}")
        except Exception as e:
            self._error_count += 1
            raise QueryError(f"Query failed: {e}")

    async def execute(self, query: str, *args, read_only: bool = False) -> QueryResult:
        """Execute query and return results"""
        start_time = time.time()

        async with self.connection(read_only=read_only) as conn:
            if query.strip().upper().startswith("SELECT"):
                rows = await conn.fetch(query, *args) if args else await conn.fetch(query)
                result = QueryResult(
                    rows=[dict(r) for r in rows],
                    row_count=len(rows),
                    last_oid=None,
                    execution_time_ms=(time.time() - start_time) * 1000
                )
            else:
                result = await conn.execute(query, *args) if args else await conn.execute(query)
                result = QueryResult(
                    rows=[],
                    row_count=0,
                    last_oid=result,
                    execution_time_ms=(time.time() - start_time) * 1000
                )

        self._query_count += 1
        self._total_query_time += (time.time() - start_time) * 1000

        return result

    async def execute_many(self, query: str, args_list: List[tuple]) -> int:
        """Execute many queries"""
        async with self.connection() as conn:
            await conn.executemany(query, args_list)
        return len(args_list)

    async def fetch(self, query: str, *args) -> List[Dict]:
        """Fetch rows"""
        async with self.connection(read_only=True) as conn:
            rows = await conn.fetch(query, *args) if args else await conn.fetch(query)
            return [dict(r) for r in rows]

    async def fetchval(self, query: str, *args) -> Any:
        """Fetch single value"""
        async with self.connection(read_only=True) as conn:
            return await conn.fetchval(query, *args) if args else await conn.fetchval(query)

    async def close(self):
        """Close connection pool"""
        if self._health_check_task:
            self._health_check_task.cancel()

        if self._pool:
            await self._pool.close()

        if self._read_pool:
            await self._read_pool.close()

        logger.info("PostgreSQL pool closed")

    def get_stats(self) -> Dict:
        """Get pool statistics"""
        return {
            "queries": self._query_count,
            "errors": self._error_count,
            "avg_query_time_ms": self._total_query_time / max(1, self._query_count),
            "healthy": self._is_healthy,
            "pool_size": self.config.pool_size,
            "read_pool_enabled": self._read_pool is not None
        }


# =============================================================================
# Redis Manager
# =============================================================================

class RedisManager:
    """
    Enterprise Redis manager for caching, queuing, locks, and pub/sub.
    """

    def __init__(self, config: DatabaseConfig):
        self.config = config
        self._client: Optional[aioredis.Redis] = None
        self._pubsub: Optional[aioredis.client.PubSub] = None
        self._lock = asyncio.Lock()

    async def initialize(self):
        """Initialize Redis connection"""
        if not REDIS_AVAILABLE:
            raise DatabaseError("redis.asyncio not installed")

        self._client = aioredis.Redis(
            host=self.config.host,
            port=self.config.port,
            password=self.config.password if self.config.password else None,
            db=0,
            decode_responses=False,
            encoding="utf-8",
        )

        # Test connection
        await self._client.ping()

        logger.info(f"Redis initialized: {self.config.host}:{self.config.port}")

    # Cache operations
    async def get(self, key: str) -> Optional[str]:
        """Get value"""
        return await self._client.get(key)

    async def set(self, key: str, value: str, expire: int = None, nx: bool = False) -> bool:
        """Set value"""
        return await self._client.set(key, value, ex=expire, nx=nx)

    async def delete(self, *keys) -> int:
        """Delete keys"""
        return await self._client.delete(*keys)

    async def exists(self, *keys) -> int:
        """Check if keys exist"""
        return await self._client.exists(*keys)

    async def expire(self, key: str, seconds: int) -> bool:
        """Set expiration"""
        return await self._client.expire(key, seconds)

    async def incr(self, key: str, amount: int = 1) -> int:
        """Increment counter"""
        return await self._client.incrby(key, amount)

    # Hash operations
    async def hget(self, key: str, field: str) -> Optional[str]:
        """Get hash field"""
        return await self._client.hget(key, field)

    async def hset(self, key: str, mapping: Dict) -> int:
        """Set hash fields"""
        return await self._client.hset(key, mapping)

    async def hgetall(self, key: str) -> Dict:
        """Get all hash fields"""
        return await self._client.hgetall(key)

    # List operations
    async def lpush(self, key: str, *values) -> int:
        """Push to list head"""
        return await self._client.lpush(key, *values)

    async def rpop(self, key: str) -> Optional[str]:
        """Pop from list tail"""
        return await self._client.rpop(key)

    async def lrange(self, key: str, start: int, end: int) -> List:
        """Get list range"""
        return await self._client.lrange(key, start, end)

    # Stream operations
    async def xadd(self, stream: str, mapping: Dict, maxlen: int = None) -> str:
        """Add to stream"""
        return await self._client.xadd(stream, mapping, maxlen=maxlen)

    async def xread(self, streams: Dict[str, str], count: int = 1, block: int = None) -> List:
        """Read from streams"""
        if block:
            return await self._client.xread(streams, count=count, block=block)
        return await self._client.xread(streams, count=count)

    async def xgroup_create(self, stream: str, group: str, start: str = "0"):
        """Create consumer group"""
        return await self._client.xgroup_create(stream, group, start)

    async def xgroup_read(self, stream: str, group: str, consumer: str, count: int = 1) -> List:
        """Read from consumer group"""
        return await self._client.xreadgroup(group, consumer, {stream: "0"}, count=count)

    # Lock operations
    async def lock_acquire(self, name: str, timeout: int = 30, worker_id: str = None) -> bool:
        """Acquire distributed lock"""
        worker_id = worker_id or str(uuid.uuid4())
        return await self._client.set(f"lock:{name}", worker_id, nx=True, ex=timeout)

    async def lock_release(self, name: str, worker_id: str) -> bool:
        """Release distributed lock"""
        lock_key = f"lock:{name}"
        current = await self._client.get(lock_key)
        if current == worker_id:
            await self._client.delete(lock_key)
            return True
        return False

    # Pub/Sub
    async def publish(self, channel: str, message: str) -> int:
        """Publish to channel"""
        return await self._client.publish(channel, message)

    async def subscribe(self, *channels: str):
        """Subscribe to channels"""
        pubsub = self._client.pubsub()
        await pubsub.subscribe(*channels)
        return pubsub

    async def close(self):
        """Close connection"""
        if self._client:
            await self._client.close()
        logger.info("Redis closed")

    def get_stats(self) -> Dict:
        """Get Redis statistics"""
        return {
            "connection": "active" if self._client else "inactive"
        }


# =============================================================================
# SQLite Vector Manager
# =============================================================================

class SQLiteVectorManager:
    """
    Lightweight local vector manager used by the local-first build.
    It avoids external vector services and keeps vectors in process for optional
    enterprise abstractions that import this module.
    """

    def __init__(self, config: DatabaseConfig):
        self.config = config
        self._vectors: Dict[int, List[float]] = {}
        self._payloads: Dict[int, Dict] = {}
        self._lock = asyncio.Lock()
        self._collection_name = "email_embeddings"

    async def initialize(self, collection_name: str = "email_embeddings"):
        self._collection_name = collection_name
        logger.info("SQLite vector manager initialized in local mode")

    async def upsert_vectors(
        self,
        vectors: List[List[float]],
        payloads: List[Dict],
        ids: List[int] = None
    ) -> bool:
        if ids is None:
            ids = list(range(len(vectors)))
        async with self._lock:
            for id_, vector, payload in zip(ids, vectors, payloads):
                self._vectors[int(id_)] = vector
                self._payloads[int(id_)] = payload
        return True

    @staticmethod
    def _cosine(a: List[float], b: List[float]) -> float:
        import math
        if not a or not b:
            return 0.0
        size = min(len(a), len(b))
        dot = sum(float(a[i]) * float(b[i]) for i in range(size))
        na = math.sqrt(sum(float(x) * float(x) for x in a[:size])) or 1.0
        nb = math.sqrt(sum(float(x) * float(x) for x in b[:size])) or 1.0
        return dot / (na * nb)

    async def search(
        self,
        query_vector: List[float],
        limit: int = 10,
        score_threshold: float = 0.1,
        query_filter: Dict = None
    ) -> List[Dict]:
        async with self._lock:
            rows = []
            for id_, vector in self._vectors.items():
                payload = self._payloads.get(id_, {})
                if query_filter and not all(payload.get(k) == v for k, v in query_filter.items()):
                    continue
                score = self._cosine(query_vector, vector)
                if score >= score_threshold:
                    rows.append({"id": id_, "score": score, "payload": payload})
        return sorted(rows, key=lambda item: item["score"], reverse=True)[:limit]

    async def delete_vectors(self, ids: List[int]) -> bool:
        async with self._lock:
            for id_ in ids:
                self._vectors.pop(int(id_), None)
                self._payloads.pop(int(id_), None)
        return True

    def get_stats(self) -> Dict:
        return {"connection": "local", "vectors": len(self._vectors), "collection": self._collection_name}


# =============================================================================
# Database Manager - Unified Interface
# =============================================================================

class DistributedDatabaseManager:
    """
    Unified distributed database manager.
    Provides unified interface to PostgreSQL, Redis, local SQLite vector storage, and object storage.
    """

    def __init__(self):
        self.config = self._load_config()

        # Initialize managers
        self.postgres: Optional[PostgresConnectionPool] = None
        self.redis: Optional[RedisManager] = None
        self.sqlite_vector: Optional[SQLiteVectorManager] = None
        self.migration_engine: Optional["MigrationEngine"] = None  # noqa: F821 — class TBD

        # Connection state
        self._initialized = False
        self._lock = asyncio.Lock()

    def _load_config(self) -> Dict[DatabaseType, DatabaseConfig]:
        """Load database configurations"""
        configs = {}

        # PostgreSQL config
        configs[DatabaseType.POSTGRESQL] = DatabaseConfig(
            db_type=DatabaseType.POSTGRESQL,
            host=os.environ.get("POSTGRES_HOST", "localhost"),
            port=int(os.environ.get("POSTGRES_PORT", "5432")),
            username=os.environ.get("POSTGRES_USER", "postgres"),
            password=os.environ.get("POSTGRES_PASSWORD", ""),
            database=os.environ.get("POSTGRES_DB", "aiemailorganizer"),
            pool_size=int(os.environ.get("POSTGRES_POOL", "20")),
        )

        # Redis config
        configs[DatabaseType.REDIS] = DatabaseConfig(
            db_type=DatabaseType.REDIS,
            host=os.environ.get("REDIS_HOST", "localhost"),
            port=int(os.environ.get("REDIS_PORT", "6379")),
            password=os.environ.get("REDIS_PASSWORD", ""),
        )

        # SQLite vector config
        configs[DatabaseType.SQLITE_VECTOR] = DatabaseConfig(
            db_type=DatabaseType.SQLITE_VECTOR,
            host=os.environ.get("SQLITE_VECTOR_HOST", "localhost"),
            port=int(os.environ.get("SQLITE_VECTOR_PORT", "0")),
        )

        return configs

    async def initialize(self):
        """Initialize all database connections"""
        async with self._lock:
            if self._initialized:
                return

            # Initialize PostgreSQL
            try:
                self.postgres = PostgresConnectionPool(
                    self.config[DatabaseType.POSTGRESQL]
                )
                await self.postgres.initialize()
                logger.info("PostgreSQL connected")
            except Exception as e:
                logger.warning(f"PostgreSQL unavailable: {e}")
                self.postgres = None

            # Initialize Redis
            try:
                self.redis = RedisManager(self.config[DatabaseType.REDIS])
                await self.redis.initialize()
                logger.info("Redis connected")
            except Exception as e:
                logger.warning(f"Redis unavailable: {e}")
                self.redis = None

            # Initialize SQLite vector
            try:
                self.sqlite_vector = SQLiteVectorManager(self.config[DatabaseType.SQLITE_VECTOR])
                await self.sqlite_vector.initialize()
                logger.info("SQLite vector manager ready")
            except Exception as e:
                logger.warning(f"SQLite vector manager unavailable: {e}")
                self.sqlite_vector = None

            # Initialize migration engine — MigrationEngine is not yet
            # implemented in this build (local-first deploys don't need it).
            # Leaving this gated path inert until the class is added.
            if self.postgres:
                logger.warning("Postgres migrations skipped: MigrationEngine not implemented")

            self._initialized = True
            logger.info("DistributedDatabaseManager initialized")

    async def close(self):
        """Close all connections"""
        if self.postgres:
            await self.postgres.close()
        if self.redis:
            await self.redis.close()

        self._initialized = False

    def get_stats(self) -> Dict:
        """Get all database stats"""
        return {
            "postgres": self.postgres.get_stats() if self.postgres else {},
            "redis": self.redis.get_stats() if self.redis else {},
            "sqlite_vector": self.sqlite_vector.get_stats() if self.sqlite_vector else {},
            "initialized": self._initialized
        }


# =============================================================================
# Register Default Migrations
# =============================================================================

def register_core_migrations(engine: "MigrationEngine"):  # noqa: F821 — class TBD
    """Register core schema migrations"""

    # Version 1: Initial schema
    engine.register_migration(
        version=1,
        description="Create initial schema",
        up_sql="""
            CREATE TABLE IF NOT EXISTS accounts (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                provider VARCHAR(50) NOT NULL,
                name VARCHAR(255),
                created_at REAL DEFAULT (EXTRACT(EPOCH FROM NOW())),
                last_sync REAL,
                sync_status VARCHAR(50) DEFAULT 'idle'
            );
            
            CREATE TABLE IF NOT EXISTS emails (
                id SERIAL PRIMARY KEY,
                account_id INTEGER REFERENCES accounts(id),
                message_id VARCHAR(255),
                subject TEXT,
                sender VARCHAR(255),
                sender_email VARCHAR(255),
                body TEXT,
                category VARCHAR(100),
                priority VARCHAR(50) DEFAULT 'Medium',
                confidence REAL DEFAULT 0.0,
                created_at REAL DEFAULT (EXTRACT(EPOCH FROM NOW())),
                synced_at REAL,
                is_read INTEGER DEFAULT 0,
                is_starred INTEGER DEFAULT 0
            );
            
            CREATE INDEX idx_emails_account ON emails(account_id);
            CREATE INDEX idx_emails_category ON emails(category);
            CREATE INDEX idx_emails_sender ON emails(sender_email);
        """,
        down_sql="""
            DROP TABLE IF EXISTS emails;
            DROP TABLE IF EXISTS accounts;
        """
    )

    # Version 2: Add rules table
    engine.register_migration(
        version=2,
        description="Add rules and feedback tables",
        up_sql="""
            CREATE TABLE IF NOT EXISTS rules (
                id SERIAL PRIMARY KEY,
                user_id INTEGER,
                name VARCHAR(255),
                category VARCHAR(100),
                subject_pattern TEXT,
                sender_pattern TEXT,
                body_pattern TEXT,
                priority VARCHAR(50),
                is_active INTEGER DEFAULT 1,
                created_at REAL DEFAULT (EXTRACT(EPOCH FROM NOW()))
            );
            
            CREATE TABLE IF NOT EXISTS feedback (
                id SERIAL PRIMARY KEY,
                email_id INTEGER REFERENCES emails(id),
                correct_category VARCHAR(100),
                correction_reason TEXT,
                created_at REAL DEFAULT (EXTRACT(EPOCH FROM NOW()))
            );
            
            CREATE INDEX idx_rules_user ON rules(user_id);
        """,
        down_sql="""
            DROP TABLE IF EXISTS feedback;
            DROP TABLE IF EXISTS rules;
        """
    )

    # Version 3: Add sync checkpoints
    engine.register_migration(
        version=3,
        description="Add sync checkpoints and event store",
        up_sql="""
            CREATE TABLE IF NOT EXISTS sync_checkpoints (
                id SERIAL PRIMARY KEY,
                account_id INTEGER REFERENCES accounts(id),
                folder VARCHAR(255),
                uid_validity INTEGER,
                last_uid INTEGER,
                checkpoint_time REAL
            );
            
            CREATE TABLE IF NOT EXISTS events (
                event_id VARCHAR(255) PRIMARY KEY,
                topic VARCHAR(255) NOT NULL,
                payload TEXT NOT NULL,
                priority INTEGER DEFAULT 2,
                correlation_id VARCHAR(255),
                source VARCHAR(255) DEFAULT 'system',
                timestamp REAL NOT NULL,
                status VARCHAR(50) DEFAULT 'pending',
                retry_count INTEGER DEFAULT 0
            );
            
            CREATE INDEX idx_events_topic ON events(topic);
            CREATE INDEX idx_events_status ON events(status);
        """,
        down_sql="""
            DROP TABLE IF EXISTS sync_checkpoints;
            DROP TABLE IF EXISTS events;
        """
    )


# =============================================================================
# Global Instance
# =============================================================================

_db_manager: Optional[DistributedDatabaseManager] = None


async def get_db_manager() -> DistributedDatabaseManager:
    """Get global database manager"""
    global _db_manager
    if _db_manager is None:
        _db_manager = DistributedDatabaseManager()
        await _db_manager.initialize()
    return _db_manager


__all__ = [
    "DatabaseConfig",
    "DatabaseType",
    "TransactionIsolation",
    "PostgresConnectionPool",
    "RedisManager",
    "SQLiteVectorManager",
    "DistributedDatabaseManager",
    "get_db_manager"
]
