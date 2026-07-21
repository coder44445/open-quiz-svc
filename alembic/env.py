from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

# Add project root to sys.path so app imports work correctly
sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
)

# Alembic configuration object (reads alembic.ini)
config = context.config

# Configure logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import SQLAlchemy Base (metadata source for autogenerate)
from app.infrastructure.database.base import Base

# Metadata used for autogenerate migrations
target_metadata = Base.metadata

# Import settings to get the database URL directly from .env
from app.core.config import settings
database_url = settings.database_url

# Ensure Alembic uses the same database URL
config.set_main_option("sqlalchemy.url", database_url)


def run_migrations_offline():
    """
    Run migrations in 'offline' mode.

    This mode does not require a database connection.
    It generates SQL scripts instead of executing them.
    """
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    """
    Actual migration execution logic.

    This runs inside a database connection.
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online():
    """
    Run migrations in 'online' mode using async database connection.
    """
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = database_url

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online_wrapper():
    """
    Wrapper to run async migrations from sync context.
    """
    asyncio.run(run_migrations_online())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online_wrapper()