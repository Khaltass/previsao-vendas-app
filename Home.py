import streamlit as st
import pandas as pd

from db import init_db, has_data
from auth import get_logged_in_email, resolve_identity_from_email

st.set_page_config(page_title="Coleta de Demanda de Vendas", page_icon="📦", layout="wide")

conn = st.session_state.get("conn") or init_db()
st.session_state["conn"] = conn

logged_email = get_logged_in_email()

if logged_email and has_data(conn) and "papel" not in st.session_state:
    resolved = resolve_identity_from_email(conn, logged_email)
    if resolved:
        st.session_state["papel"], st.session_state["identidade_codigo"], st.session_state["identidade_nome"] = resolved

papel = st.session_state.get("papel")


def render_home():
    st.title("📦 App Piloto — Coleta de Demanda de Volume de Vendas")

    if not has_data(conn):
        st.warning(
            "Nenhuma planilha carregada ainda. Vá até a página **Upload** no menu lateral "
            "para carregar a planilha com as abas Hierarquia, Produtos e Volumes."
        )
        return

    if logged_email:
        st.success(f"Login corporativo detectado: **{logged_email}**")
        if papel:
            st.info(
                f"Perfil identificado automaticamente: **{papel}** — **{st.session_state['identidade_nome']}**. "
                "Use o menu lateral para acessar sua tela de trabalho."
            )
        else:
            st.error(
                f"Seu e-mail (**{logged_email}**) não foi encontrado na aba Hierarquia da planilha carregada. "
                "Peça para um administrador incluir seu e-mail na coluna correspondente "
                "(E-mail do Vendedor, do Supervisor ou do Gerente Regional) e recarregar a base."
            )
        return

    st.success("Dados carregados. Selecione seu perfil e identidade abaixo para navegar no app.")
    st.caption("Modo de teste local — sem login corporativo detectado, escolha manualmente o perfil para simular.")

    st.subheader("Perfil simulado")

    perfil = st.selectbox(
        "Perfil de acesso",
        ["Vendedor", "Supervisor", "Gerente Regional"],
        key="perfil_select",
    )

    if perfil == "Vendedor":
        df = pd.read_sql_query(
            "SELECT DISTINCT vendedor_codigo, vendedor_nome FROM volumes ORDER BY vendedor_nome", conn
        )
        if df.empty:
            st.info("Nenhum vendedor encontrado nos dados carregados.")
        else:
            options = df.apply(lambda r: f"{r['vendedor_nome']} ({r['vendedor_codigo']})", axis=1).tolist()
            escolha = st.selectbox("Vendedor", options, key="identidade_vendedor")
            idx = options.index(escolha)
            st.session_state["papel"] = "Vendedor"
            st.session_state["identidade_codigo"] = df.iloc[idx]["vendedor_codigo"]
            st.session_state["identidade_nome"] = df.iloc[idx]["vendedor_nome"]

    elif perfil == "Supervisor":
        df = pd.read_sql_query(
            "SELECT DISTINCT supervisor_nome FROM volumes ORDER BY supervisor_nome", conn
        )
        if df.empty:
            st.info("Nenhum supervisor encontrado nos dados carregados.")
        else:
            escolha = st.selectbox("Supervisor", df["supervisor_nome"].tolist(), key="identidade_supervisor")
            st.session_state["papel"] = "Supervisor"
            st.session_state["identidade_codigo"] = escolha
            st.session_state["identidade_nome"] = escolha

    else:
        df = pd.read_sql_query(
            "SELECT DISTINCT regional_descricao FROM volumes ORDER BY regional_descricao", conn
        )
        if df.empty:
            st.info("Nenhuma regional encontrada nos dados carregados.")
        else:
            escolha = st.selectbox("Regional", df["regional_descricao"].tolist(), key="identidade_regional")
            st.session_state["papel"] = "Gerente Regional"
            st.session_state["identidade_codigo"] = escolha
            st.session_state["identidade_nome"] = escolha

    st.info(
        f"Perfil ativo: **{st.session_state.get('papel', '-')}** — "
        f"**{st.session_state.get('identidade_nome', '-')}**. "
        "Use o menu lateral para acessar sua tela de trabalho."
    )


home_page = st.Page(render_home, title="Home", icon="🏠", default=True)
upload_page = st.Page("pages/1_📤_Upload.py", title="Upload", icon="📤")
vendedor_page = st.Page("pages/2_🧑‍💼_Vendedor.py", title="Vendedor", icon="🧑‍💼")
supervisor_page = st.Page("pages/3_👥_Supervisor.py", title="Supervisor", icon="👥")
gerente_page = st.Page("pages/4_🏢_Gerente_Regional.py", title="Gerente Regional", icon="🏢")
consolidacao_page = st.Page("pages/5_📊_Consolidacao.py", title="Consolidação", icon="📊")
status_page = st.Page("pages/6_✅_Status_Envio.py", title="Status de Envio", icon="✅")
backlog_page = st.Page("pages/7_📋_Backlog.py", title="Backlog", icon="📋")

if logged_email and papel:
    # login corporativo com perfil identificado: acesso restrito somente à tela da alçada
    # (Supervisor e Gerente Regional também enxergam o painel de status/aprovação)
    role_pages = {
        "Vendedor": [vendedor_page],
        "Supervisor": [supervisor_page, status_page],
        "Gerente Regional": [gerente_page, status_page],
    }
    pages = [home_page] + role_pages.get(papel, [])
elif logged_email:
    # login corporativo mas e-mail não associado a nenhum perfil na planilha
    pages = [home_page]
else:
    # sem login corporativo (uso local/administrativo): acesso completo para testes
    pages = [home_page, upload_page, vendedor_page, supervisor_page, gerente_page, consolidacao_page, status_page]

# Backlog de melhorias: fica disponível em qualquer modo de acesso, já que não
# depende da planilha carregada nem do perfil (é uma ferramenta de gestão do próprio app).
pages = pages + [backlog_page]

pg = st.navigation(pages)
pg.run()
