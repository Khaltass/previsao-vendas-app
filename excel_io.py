"""Parsing e validação da planilha de upload (3 abas) e carga no SQLite."""
import unicodedata
import pandas as pd

from models import horizon_for_family, month_label_for_cycle
from db import now_iso


class ValidationError(Exception):
    pass


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.strip().lower().replace("_", " ").replace("-", " ")
    # colapsa espaços múltiplos depois


def _norm_key(text: str) -> str:
    n = _normalize(text)
    return " ".join(n.split())


# aliases: nome interno -> lista de nomes aceitos na planilha (normalizados)
HIERARCHY_COLS = {
    "vendedor_codigo": ["codigo do vendedor"],
    "vendedor_nome": ["nome do vendedor", "nome_do_vendedor"],
    "supervisor_nome": ["nome do supervisor"],
    "regional_descricao": ["descricao regional"],
}

# colunas opcionais: usadas para o login corporativo (perfil detectado pelo e-mail),
# ausentes até que a planilha seja atualizada com os e-mails de cada pessoa
HIERARCHY_OPTIONAL_COLS = {
    "vendedor_email": ["email do vendedor", "e-mail do vendedor"],
    "supervisor_email": ["email do supervisor", "e-mail do supervisor"],
    "regional_email": ["email do gerente regional", "e-mail do gerente regional", "email da regional", "e-mail da regional"],
}

PRODUCTS_COLS = {
    "produto_codigo": ["codigo do produto"],
    "produto_descricao": ["descricao do produto"],
    "grupo_descricao": ["descricao do grupo"],
}

VOLUMES_COLS = {
    "chave": ["chave"],
    "cliente_nome": ["nome do cliente"],
    "regional_descricao": ["descricao regional"],
    "supervisor_nome": ["nome do supervisor"],
    "grupo_descricao": ["descricao do grupo"],
    "vendedor_codigo": ["codigo do vendedor"],
    "vendedor_nome": ["nome do vendedor", "nome_do_vendedor"],
    "produto_codigo": ["codigo do produto"],
    "produto_descricao": ["descricao do produto"],
    "media_6m": ["media 6 meses kg"],
    "media_3m": ["media 3 meses kg"],
    "minimo": ["minimo"],
    "maximo": ["maximo"],
    "ultimo_mes": ["ultimo mes"],
}

# opcional: agrupa clientes com mais de uma loja ("redes"). Ausente até que a
# planilha seja atualizada com essa coluna — nesse caso cada cliente forma seu
# próprio grupo (ver fallback em parse_workbook).
VOLUMES_OPTIONAL_COLS = {
    "grupo_cliente": ["grupo do cliente", "grupo cliente", "rede", "nome do grupo do cliente"],
}

SHEET_ALIASES = {
    "hierarquia": ["hierarquia"],
    "produtos": ["produtos", "cadastro de produtos"],
    "volumes": ["volumes", "tabela de volumes"],
}


def _find_sheet(xls: pd.ExcelFile, aliases) -> str:
    norm_names = {name: _norm_key(name) for name in xls.sheet_names}
    for name, norm in norm_names.items():
        if any(alias in norm for alias in aliases):
            return name
    return None


def _rename_columns(df: pd.DataFrame, col_map: dict, sheet_label: str, optional_cols: dict = None) -> pd.DataFrame:
    norm_to_original = {_norm_key(c): c for c in df.columns}
    rename = {}
    missing = []
    for internal, aliases in col_map.items():
        found = None
        for alias in aliases:
            if alias in norm_to_original:
                found = norm_to_original[alias]
                break
        if found is None:
            missing.append(f"{internal} (esperado: '{aliases[0]}')")
        else:
            rename[found] = internal
    if missing:
        raise ValidationError(
            f"Colunas obrigatórias ausentes na aba '{sheet_label}': " + "; ".join(missing)
        )
    result = df.rename(columns=rename)[list(col_map.keys())]

    for internal, aliases in (optional_cols or {}).items():
        found = None
        for alias in aliases:
            if alias in norm_to_original:
                found = norm_to_original[alias]
                break
        result[internal] = df[found] if found is not None else None
    return result


def parse_workbook(file) -> dict:
    """Lê o .xlsx enviado e retorna {'hierarchy': df, 'products': df, 'volumes': df}
    já validados e com colunas normalizadas. Lança ValidationError em caso de problema.
    """
    try:
        xls = pd.ExcelFile(file)
    except Exception as exc:
        raise ValidationError(f"Não foi possível abrir o arquivo Excel: {exc}")

    sheet_h = _find_sheet(xls, SHEET_ALIASES["hierarquia"])
    sheet_p = _find_sheet(xls, SHEET_ALIASES["produtos"])
    sheet_v = _find_sheet(xls, SHEET_ALIASES["volumes"])

    missing_sheets = []
    if not sheet_h:
        missing_sheets.append("Hierarquia")
    if not sheet_p:
        missing_sheets.append("Produtos")
    if not sheet_v:
        missing_sheets.append("Volumes")
    if missing_sheets:
        raise ValidationError(
            "Abas não encontradas na planilha: " + ", ".join(missing_sheets) +
            f". Abas disponíveis: {', '.join(xls.sheet_names)}"
        )

    df_h = _rename_columns(pd.read_excel(xls, sheet_h, dtype=str), HIERARCHY_COLS, "Hierarquia", optional_cols=HIERARCHY_OPTIONAL_COLS)
    df_p = _rename_columns(pd.read_excel(xls, sheet_p, dtype=str), PRODUCTS_COLS, "Produtos")

    # dtype=str em toda a leitura evita que o pandas infira colunas de código
    # (ex: "000335") como numéricas e perca os zeros à esquerda.
    df_v_raw = pd.read_excel(xls, sheet_v, dtype=str)
    df_v = _rename_columns(df_v_raw, VOLUMES_COLS, "Volumes", optional_cols=VOLUMES_OPTIONAL_COLS)

    key_cols = ["chave", "cliente_nome", "vendedor_codigo", "produto_codigo"]
    for c in key_cols:
        df_v[c] = df_v[c].str.strip()
    # remove linhas de rodapé/lixo (em branco ou texto de filtro exportado pela ferramenta de BI)
    df_v = df_v[df_v[key_cols].notna().all(axis=1) & (df_v[key_cols] != "").all(axis=1)]

    numeric_cols = ["media_6m", "media_3m", "minimo", "maximo", "ultimo_mes"]
    for c in numeric_cols:
        df_v[c] = pd.to_numeric(df_v[c].astype(str).str.strip(), errors="coerce")
    text_cols = [c for c in VOLUMES_COLS if c not in numeric_cols]
    for c in text_cols:
        df_v[c] = df_v[c].astype(str).str.strip()

    # grupo_cliente é opcional na planilha; sem ele, cada cliente forma seu próprio grupo.
    df_v["grupo_cliente"] = df_v["grupo_cliente"].where(df_v["grupo_cliente"].notna(), None)
    df_v["grupo_cliente"] = df_v["grupo_cliente"].apply(lambda v: v.strip() if isinstance(v, str) else v)
    sem_grupo = df_v["grupo_cliente"].isna() | (df_v["grupo_cliente"] == "")
    df_v.loc[sem_grupo, "grupo_cliente"] = df_v.loc[sem_grupo, "cliente_nome"]

    for c in df_h.columns:
        if c in HIERARCHY_OPTIONAL_COLS:
            continue
        df_h[c] = df_h[c].astype(str).str.strip()
    for c in HIERARCHY_OPTIONAL_COLS:
        df_h[c] = df_h[c].where(df_h[c].notna(), None)
        df_h[c] = df_h[c].apply(lambda v: v.strip() or None if isinstance(v, str) else v)
    for c in df_p.columns:
        df_p[c] = df_p[c].astype(str).str.strip()

    return {"hierarchy": df_h, "products": df_p, "volumes": df_v}


def load_into_db(conn, parsed: dict, cycle_year: int, cycle_month: int):
    """Grava as três tabelas e (re)inicializa as projeções mensais por família.

    `cycle_year`/`cycle_month` definem a Data Ciclo: os rótulos das colunas de
    projeção (month_label) são gerados a partir dela, ex. ciclo Jul/26 -> Ago/26, Set/26, ...
    """
    df_h, df_p, df_v = parsed["hierarchy"], parsed["products"], parsed["volumes"]

    cur = conn.cursor()
    hierarchy_cols = [
        "vendedor_codigo", "vendedor_nome", "supervisor_nome", "regional_descricao",
        "vendedor_email", "supervisor_email", "regional_email",
    ]
    cur.executemany(
        f"INSERT INTO raw_hierarchy ({', '.join(hierarchy_cols)}) "
        f"VALUES ({', '.join(['?'] * len(hierarchy_cols))})",
        df_h[hierarchy_cols].values.tolist(),
    )
    cur.executemany(
        "INSERT INTO raw_products (produto_codigo, produto_descricao, grupo_descricao) VALUES (?, ?, ?)",
        df_p[["produto_codigo", "produto_descricao", "grupo_descricao"]].values.tolist(),
    )

    vol_cols = [
        "chave", "cliente_nome", "grupo_cliente", "regional_descricao", "supervisor_nome", "grupo_descricao",
        "vendedor_codigo", "vendedor_nome", "produto_codigo", "produto_descricao",
        "media_6m", "media_3m", "minimo", "maximo", "ultimo_mes",
    ]
    vol_update_cols = [c for c in vol_cols if c not in ("chave", "produto_codigo")]
    cur.executemany(
        f"INSERT INTO volumes ({', '.join(vol_cols)}) "
        f"VALUES ({', '.join(['?'] * len(vol_cols))}) "
        f"ON CONFLICT (chave, produto_codigo) DO UPDATE SET "
        + ", ".join(f"{c} = excluded.{c}" for c in vol_update_cols),
        df_v[vol_cols].values.tolist(),
    )

    ts = now_iso()
    proj_rows = []
    for _, row in df_v.iterrows():
        horizon = horizon_for_family(row["grupo_descricao"])
        if pd.notna(row["media_3m"]):
            media_3m = row["media_3m"]
        elif pd.notna(row["media_6m"]):
            media_3m = row["media_6m"]
        else:
            media_3m = 0.0
        # Só pré-preenche quando o cliente comprou no último mês (há demanda recorrente
        # para basear a sugestão); quem não comprou fica com projeção zerada até o
        # vendedor preencher manualmente.
        comprou_ultimo_mes = pd.notna(row["ultimo_mes"]) and row["ultimo_mes"] > 0
        valor_inicial = media_3m if comprou_ultimo_mes else 0.0
        for m in range(1, horizon + 1):
            label = month_label_for_cycle(cycle_year, cycle_month, m)
            proj_rows.append(
                (row["chave"], row["produto_codigo"], m, label, valor_inicial, valor_inicial, "vendedor", None, ts)
            )
    proj_cols = [
        "chave", "produto_codigo", "month_index", "month_label", "current_value", "vendor_value",
        "last_changed_level", "last_changed_by", "last_changed_at",
    ]
    proj_update_cols = [c for c in proj_cols if c not in ("chave", "produto_codigo", "month_index")]
    cur.executemany(
        f"INSERT INTO projection_values ({', '.join(proj_cols)}) "
        f"VALUES ({', '.join(['?'] * len(proj_cols))}) "
        f"ON CONFLICT (chave, produto_codigo, month_index) DO UPDATE SET "
        + ", ".join(f"{c} = excluded.{c}" for c in proj_update_cols),
        proj_rows,
    )
    conn.commit()
    return {
        "hierarquia": len(df_h),
        "produtos": len(df_p),
        "volumes": len(df_v),
        "projecoes": len(proj_rows),
    }
