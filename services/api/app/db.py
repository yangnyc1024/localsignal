from collections.abc import Iterator

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import settings


pool = ConnectionPool(settings.database_url, kwargs={"row_factory": dict_row})


def get_connection() -> Iterator:
    with pool.connection() as conn:
        yield conn
