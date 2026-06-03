"""Central database connection factory.

All callers should use get_conn() / get_dict_conn() instead of calling
psycopg.connect() directly. This keeps the DATABASE_URL lookup and any
future pool/retry logic in one place.
"""
import os
from contextlib import contextmanager
from typing import Any, Generator

import psycopg
from psycopg.rows import dict_row


def _database_url(required: bool = True) -> str:
    url = os.getenv("DATABASE_URL", "")
    if required and not url:
        raise RuntimeError("DATABASE_URL environment variable is not set.")
    return url


@contextmanager
def get_conn(**kwargs: Any) -> Generator[psycopg.Connection, None, None]:
    """Context manager that yields a plain psycopg connection."""
    with psycopg.connect(_database_url(), **kwargs) as conn:
        yield conn


@contextmanager
def get_dict_conn(**kwargs: Any) -> Generator[psycopg.Connection, None, None]:
    """Context manager that yields a connection with dict_row factory."""
    with psycopg.connect(_database_url(), row_factory=dict_row, **kwargs) as conn:
        yield conn
