"""Helpers de UI reutilizados pelas páginas do app."""
import streamlit as st


def fmt_milhar(v, decimals: int = 0) -> str:
    """Formata um número com separador de milhar padrão brasileiro (ponto).

    Usado em todas as tabelas de exibição do app para facilitar a leitura de
    volumes grandes. Com `decimals > 0`, a casa decimal usa vírgula (formato
    pt-BR completo); com `decimals = 0` (padrão), é só o separador de milhar.
    """
    if v is None or v == "" or (isinstance(v, float) and v != v):
        return "-"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    txt = f"{v:,.{decimals}f}"
    return txt.replace(",", "@").replace(".", ",").replace("@", ".")


def filter_dataframe(df, key, label="🔍 Filtrar tabela"):
    """Campo de texto que filtra as linhas do dataframe por qualquer coluna (case-insensitive).

    Sempre reindexa (0..n-1) o resultado, já que várias telas alinham edições
    de volta ao dataframe original por posição (.iloc) após a filtragem.
    """
    query = st.text_input(label, key=key, placeholder="Digite para filtrar por qualquer coluna...")
    if not query:
        return df.reset_index(drop=True)
    mask = df.astype(str).apply(lambda col: col.str.contains(query, case=False, na=False, regex=False))
    return df[mask.any(axis=1)].reset_index(drop=True)
