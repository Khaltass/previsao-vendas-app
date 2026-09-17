"""Conexão com o banco (SQLite local ou Postgres/Supabase) e schema do app piloto.

Se a secret/variável de ambiente DATABASE_URL estiver definida, conecta no Postgres
(pensado para o Supabase). Caso contrário, cai no SQLite local em data/app.db —
o mesmo comportamento de sempre, usado para desenvolvimento sem depender de nada externo.

O resto do app (páginas, excel_io.py) continua escrevendo SQL no estilo SQLite
(placeholders "?", `conn.execute(...)`, linhas acessíveis por `row["coluna"]`).
Os wrappers abaixo traduzem isso para o Postgres nos bastidores, então nenhuma
outra parte do código precisa saber qual banco está por trás.
"""
import os
import sqlite3
from pathlib import Path
from datetime import datetime

import streamlit as st

DB_PATH = Path(__file__).parent / "data" / "app.db"

SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS raw_hierarchy (
    vendedor_codigo TEXT,
    vendedor_nome TEXT,
    supervisor_nome TEXT,
    regional_descricao TEXT,
    vendedor_email TEXT,
    supervisor_email TEXT,
    regional_email TEXT
);

CREATE TABLE IF NOT EXISTS raw_products (
    produto_codigo TEXT,
    produto_descricao TEXT,
    grupo_descricao TEXT
);

CREATE TABLE IF NOT EXISTS volumes (
    chave TEXT,
    cliente_nome TEXT,
    grupo_cliente TEXT,
    regional_descricao TEXT,
    supervisor_nome TEXT,
    grupo_descricao TEXT,
    vendedor_codigo TEXT,
    vendedor_nome TEXT,
    produto_codigo TEXT,
    produto_descricao TEXT,
    media_6m REAL,
    media_3m REAL,
    minimo REAL,
    maximo REAL,
    ultimo_mes REAL,
    PRIMARY KEY (chave, produto_codigo)
);

CREATE TABLE IF NOT EXISTS projection_values (
    chave TEXT,
    produto_codigo TEXT,
    month_index INTEGER,
    month_label TEXT,
    current_value REAL,
    vendor_value REAL,
    last_changed_level TEXT,
    last_changed_by TEXT,
    last_changed_at TEXT,
    PRIMARY KEY (chave, produto_codigo, month_index)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chave TEXT,
    produto_codigo TEXT,
    month_index INTEGER,
    changed_by_role TEXT,
    changed_by_name TEXT,
    old_value REAL,
    new_value REAL,
    changed_at TEXT
);

CREATE TABLE IF NOT EXISTS app_config (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS manual_adjustments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level TEXT,
    scope_name TEXT,
    chave TEXT,
    cliente_nome TEXT,
    produto_codigo TEXT,
    month_index INTEGER,
    month_label TEXT,
    value REAL,
    created_by TEXT,
    created_at TEXT,
    note TEXT
);

CREATE TABLE IF NOT EXISTS submission_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level TEXT,              -- 'vendedor' ou 'supervisor'
    scope_codigo TEXT,       -- vendedor_codigo (nível vendedor) ou supervisor_nome (nível supervisor)
    scope_nome TEXT,
    parent_scope TEXT,       -- supervisor_nome (nível vendedor) ou regional_descricao (nível supervisor)
    enviado INTEGER DEFAULT 0,
    enviado_em TEXT,
    enviado_por TEXT,
    status_aprovacao TEXT DEFAULT 'Pendente',
    aprovado_por TEXT,
    aprovado_em TEXT,
    UNIQUE (level, scope_codigo)
);

"""

# Igual ao schema SQLite, exceto id INTEGER PRIMARY KEY AUTOINCREMENT -> SERIAL PRIMARY KEY
# (sintaxe do SQLite não existe no Postgres).
SCHEMA_POSTGRES = """
CREATE TABLE IF NOT EXISTS raw_hierarchy (
    vendedor_codigo TEXT,
    vendedor_nome TEXT,
    supervisor_nome TEXT,
    regional_descricao TEXT,
    vendedor_email TEXT,
    supervisor_email TEXT,
    regional_email TEXT
);

CREATE TABLE IF NOT EXISTS raw_products (
    produto_codigo TEXT,
    produto_descricao TEXT,
    grupo_descricao TEXT
);

CREATE TABLE IF NOT EXISTS volumes (
    chave TEXT,
    cliente_nome TEXT,
    grupo_cliente TEXT,
    regional_descricao TEXT,
    supervisor_nome TEXT,
    grupo_descricao TEXT,
    vendedor_codigo TEXT,
    vendedor_nome TEXT,
    produto_codigo TEXT,
    produto_descricao TEXT,
    media_6m REAL,
    media_3m REAL,
    minimo REAL,
    maximo REAL,
    ultimo_mes REAL,
    PRIMARY KEY (chave, produto_codigo)
);

CREATE TABLE IF NOT EXISTS projection_values (
    chave TEXT,
    produto_codigo TEXT,
    month_index INTEGER,
    month_label TEXT,
    current_value REAL,
    vendor_value REAL,
    last_changed_level TEXT,
    last_changed_by TEXT,
    last_changed_at TEXT,
    PRIMARY KEY (chave, produto_codigo, month_index)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    chave TEXT,
    produto_codigo TEXT,
    month_index INTEGER,
    changed_by_role TEXT,
    changed_by_name TEXT,
    old_value REAL,
    new_value REAL,
    changed_at TEXT
);

CREATE TABLE IF NOT EXISTS app_config (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS manual_adjustments (
    id SERIAL PRIMARY KEY,
    level TEXT,
    scope_name TEXT,
    chave TEXT,
    cliente_nome TEXT,
    produto_codigo TEXT,
    month_index INTEGER,
    month_label TEXT,
    value REAL,
    created_by TEXT,
    created_at TEXT,
    note TEXT
);

CREATE TABLE IF NOT EXISTS submission_status (
    id SERIAL PRIMARY KEY,
    level TEXT,
    scope_codigo TEXT,
    scope_nome TEXT,
    parent_scope TEXT,
    enviado INTEGER DEFAULT 0,
    enviado_em TEXT,
    enviado_por TEXT,
    status_aprovacao TEXT DEFAULT 'Pendente',
    aprovado_por TEXT,
    aprovado_em TEXT,
    UNIQUE (level, scope_codigo)
);

"""


class _PgRow(tuple):
    """Uma linha de resultado que se comporta como sqlite3.Row: tupla posicional
    de verdade (é isso que o pandas espera ao iterar `cursor.fetchall()`), mas
    também aceita indexação por nome de coluna (`row["coluna"]`, usado em todo
    o resto do app). Usar dict (ex: RealDictCursor) aqui quebra o pandas, porque
    iterar um dict devolve as chaves, não os valores."""

    def __new__(cls, values, columns):
        obj = super().__new__(cls, values)
        obj._columns = columns
        return obj

    def __getitem__(self, key):
        if isinstance(key, str):
            return tuple.__getitem__(self, self._columns.index(key))
        return tuple.__getitem__(self, key)

    def keys(self):
        return list(self._columns)


class _PgCursor:
    """Encapsula um cursor psycopg2 para aceitar SQL escrito com placeholders "?"
    (estilo sqlite3) usado em todo o resto do app."""

    def __init__(self, real_cursor):
        self._cur = real_cursor

    @staticmethod
    def _translate(sql: str) -> str:
        return sql.replace("?", "%s")

    def execute(self, sql, params=()):
        self._cur.execute(self._translate(sql), params)
        return self

    def executemany(self, sql, seq_of_params):
        self._cur.executemany(self._translate(sql), seq_of_params)
        return self

    def _wrap(self, row):
        if row is None:
            return None
        columns = [d[0] for d in self._cur.description]
        return _PgRow(row, columns)

    def fetchone(self):
        return self._wrap(self._cur.fetchone())

    def fetchall(self):
        return [self._wrap(row) for row in self._cur.fetchall()]

    def close(self):
        self._cur.close()

    def __iter__(self):
        return iter(self.fetchall())

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @property
    def rowcount(self):
        return self._cur.rowcount

    @property
    def description(self):
        return self._cur.description


class _PgConnection:
    """Encapsula uma conexão psycopg2 para expor a mesma API sqlite3 que o
    resto do app já usa (`conn.execute(...)`, `conn.cursor()`, linhas com
    `row["coluna"]` via _PgRow)."""

    def __init__(self, pg_conn):
        self._conn = pg_conn

    def cursor(self):
        return _PgCursor(self._conn.cursor())

    def execute(self, sql, params=()):
        cur = self.cursor()
        cur.execute(sql, params)
        return cur

    def executescript(self, script: str):
        with self._conn.cursor() as cur:
            cur.execute(script)

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


def _database_url():
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    try:
        return st.secrets["DATABASE_URL"]
    except Exception:
        return None


def get_conn():
    url = _database_url()
    if url:
        import psycopg2

        pg_conn = psycopg2.connect(url)
        return _PgConnection(pg_conn)

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    if isinstance(conn, _PgConnection):
        conn.executescript(SCHEMA_POSTGRES)
        _migrate_postgres(conn)
    else:
        conn.executescript(SCHEMA_SQLITE)
        _migrate_sqlite(conn)
    conn.commit()
    return conn


def _migrate_sqlite(conn):
    """Adiciona colunas novas em bancos já existentes (CREATE TABLE IF NOT EXISTS não altera tabelas já criadas)."""
    hier_cols = {row["name"] for row in conn.execute("PRAGMA table_info(raw_hierarchy)")}
    for col in ("vendedor_email", "supervisor_email", "regional_email"):
        if col not in hier_cols:
            conn.execute(f"ALTER TABLE raw_hierarchy ADD COLUMN {col} TEXT")

    vol_cols = {row["name"] for row in conn.execute("PRAGMA table_info(volumes)")}
    if "grupo_cliente" not in vol_cols:
        conn.execute("ALTER TABLE volumes ADD COLUMN grupo_cliente TEXT")


def _migrate_postgres(conn):
    def _existing_cols(table):
        cur = conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ?", (table,)
        )
        return {row["column_name"] for row in cur.fetchall()}

    hier_cols = _existing_cols("raw_hierarchy")
    for col in ("vendedor_email", "supervisor_email", "regional_email"):
        if col not in hier_cols:
            conn.execute(f"ALTER TABLE raw_hierarchy ADD COLUMN {col} TEXT")

    vol_cols = _existing_cols("volumes")
    if "grupo_cliente" not in vol_cols:
        conn.execute("ALTER TABLE volumes ADD COLUMN grupo_cliente TEXT")


def reset_data(conn):
    """Limpa todas as tabelas antes de uma nova carga de planilha."""
    tables = [
        "raw_hierarchy",
        "raw_products",
        "volumes",
        "projection_values",
        "audit_log",
        "manual_adjustments",
        "submission_status",
    ]
    for t in tables:
        conn.execute(f"DELETE FROM {t}")
    conn.commit()


def has_data(conn) -> bool:
    row = conn.execute("SELECT COUNT(*) AS c FROM volumes").fetchone()
    return row["c"] > 0


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_config(conn, key: str, default=None):
    row = conn.execute("SELECT value FROM app_config WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_config(conn, key: str, value):
    conn.execute(
        "INSERT INTO app_config (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )
    conn.commit()
