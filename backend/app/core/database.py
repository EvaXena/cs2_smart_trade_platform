# -*- coding: utf-8 -*-
"""
数据库连接配置
"""
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import text
from sqlalchemy.pool import StaticPool

from app.core.config import settings


# 判断是否为 SQLite 数据库
is_sqlite = settings.DATABASE_URL.startswith("sqlite")

if is_sqlite:
    # SQLite 配置优化
    # 确保URL是aiosqlite格式
    if "+aiosqlite" not in settings.DATABASE_URL:
        db_url = settings.DATABASE_URL.replace("sqlite:///", "sqlite+aiosqlite:///")
    else:
        db_url = settings.DATABASE_URL
    
    engine = create_async_engine(
        db_url,
        echo=settings.DEBUG,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        pool_pre_ping=True,
    )
    
    # 配置 SQLite WAL 模式和 busy_timeout
    async def configure_sqlite(engine):
        """配置 SQLite 优化参数"""
        async with engine.begin() as conn:
            # 启用 WAL 模式（提高并发性能）
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            # 设置 busy_timeout（等待锁释放的时间）
            await conn.execute(text("PRAGMA busy_timeout=30000"))
            # 启用外键约束
            await conn.execute(text("PRAGMA foreign_keys=ON"))
            # 同步模式设为 NORMAL（WAL模式下推荐）
            await conn.execute(text("PRAGMA synchronous=NORMAL"))
            # 设置缓存大小（负数表示KB）
            await conn.execute(text("PRAGMA cache_size=-2000"))
            # 启用内存模式共享
            await conn.execute(text("PRAGMA mmap_size=268435456"))
    
    # 应用 SQLite 配置
    # 注意：这里不能使用 run_until_complete 因为这可能在事件循环已运行时导致崩溃
    # 改为在应用启动时通过 lifespan 来配置
    # 存储配置函数供后续调用
    
    def configure_sqlite_sync():
        """同步版本的 SQLite 配置（用于非异步环境）"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(configure_sqlite(engine))
        finally:
            loop.close()
    
    # 只有在没有运行事件循环时才同步配置
    try:
        loop = asyncio.get_running_loop()
        # 事件循环正在运行，标记需要延迟配置
        _delayed_sqlite_config = engine
    except RuntimeError:
        # 没有运行中的事件循环，可以安全同步配置
        configure_sqlite_sync()
else:
    # PostgreSQL/MySQL 配置
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=settings.DEBUG,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        pool_recycle=3600,
        pool_timeout=30,
    )

# 创建会话工厂
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# 创建基类
Base = declarative_base()


async def get_db() -> AsyncSession:
    """获取数据库会话依赖"""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
