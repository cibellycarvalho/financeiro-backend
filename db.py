from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool
import config

_pool = None

def get_pool():
    global _pool
    if _pool is None:
        _pool = ThreadedConnectionPool(2, 10, config.DATABASE_URL)
    return _pool

def query(sql: str, params: tuple = ()) -> list[dict]:
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]
    finally:
        pool.putconn(conn)

def execute(sql: str, params: tuple = ()) -> dict | None:
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            conn.commit()
            if cur.description:
                row = cur.fetchone()
                return dict(row) if row else None
            return None
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)

@contextmanager
def transaction():
    """Cursor de várias instruções numa transação só: commit no fim do bloco,
    rollback se qualquer instrução levantar exceção."""
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)
