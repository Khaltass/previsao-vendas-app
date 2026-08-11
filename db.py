"""Conexão SQLite e schema para o app piloto de coleta de demanda."""
import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "data" / "app.db"

SCHEMA = """
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


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()
    return conn


def _migrate(conn):
    """Adiciona colunas novas em bancos já existentes (CREATE TABLE IF NOT EXISTS não altera tabelas já criadas)."""
    existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(raw_hierarchy)")}
    for col in ("vendedor_email", "supervisor_email", "regional_email"):
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE raw_hierarchy ADD COLUMN {col} TEXT")


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
