"""Login corporativo via Azure App Service Authentication (Easy Auth) ligado ao Entra ID.

Fora do Azure (ex.: rodando localmente), não há cabeçalhos de autenticação e o app
cai no modo manual de seleção de perfil já existente — nada muda para uso local/teste.
"""
import streamlit as st

_PRINCIPAL_HEADER_CANDIDATES = ("X-Ms-Client-Principal-Name", "X-MS-CLIENT-PRINCIPAL-NAME")


def get_logged_in_email():
    """Retorna o e-mail/UPN do usuário autenticado pelo Azure App Service, ou None fora desse ambiente."""
    try:
        headers = st.context.headers
    except Exception:
        return None
    for key in _PRINCIPAL_HEADER_CANDIDATES:
        value = headers.get(key)
        if value:
            return value.strip()
    return None


def resolve_identity_from_email(conn, email: str):
    """Cruza o e-mail logado com a Hierarquia carregada.

    Retorna (papel, identidade_codigo, identidade_nome) na primeira correspondência
    encontrada (Vendedor -> Supervisor -> Gerente Regional), ou None se o e-mail não
    estiver associado a ninguém na planilha carregada.
    """
    email_norm = email.strip().lower()

    row = conn.execute(
        "SELECT vendedor_codigo, vendedor_nome FROM raw_hierarchy WHERE LOWER(vendedor_email) = ? LIMIT 1",
        (email_norm,),
    ).fetchone()
    if row:
        return "Vendedor", row["vendedor_codigo"], row["vendedor_nome"]

    row = conn.execute(
        "SELECT supervisor_nome FROM raw_hierarchy WHERE LOWER(supervisor_email) = ? LIMIT 1",
        (email_norm,),
    ).fetchone()
    if row:
        return "Supervisor", row["supervisor_nome"], row["supervisor_nome"]

    row = conn.execute(
        "SELECT regional_descricao FROM raw_hierarchy WHERE LOWER(regional_email) = ? LIMIT 1",
        (email_norm,),
    ).fetchone()
    if row:
        return "Gerente Regional", row["regional_descricao"], row["regional_descricao"]

    return None
