from datetime import date

import streamlit as st

from db import init_db, reset_data, has_data, get_config, set_config
from excel_io import parse_workbook, load_into_db, ValidationError
from models import month_label_for_cycle

MESES_NOMES = [
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]

conn = st.session_state.get("conn") or init_db()
st.session_state["conn"] = conn

st.title("📤 Upload da planilha de demanda")

st.markdown(
    """
Envie um arquivo **.xlsx** com três abas:

1. **Hierarquia** — Código do Vendedor, Nome do Vendedor, Nome do Supervisor, Descrição Regional
   (opcional, para login corporativo: Email do Vendedor, Email do Supervisor, Email do Gerente Regional)
2. **Produtos** — Código do Produto, Descrição do Produto, Descrição do Grupo
3. **Volumes** — Chave, Nome do Cliente, Descrição Regional, Nome do Supervisor, Descrição do Grupo,
   Código do Vendedor, Nome do Vendedor, Código do Produto, Descrição do Produto,
   Media 6 Meses Kg, Media 3 Meses Kg, **Mínimo**, **Máximo**, Ultimo Mês

⚠️ Um novo upload **substitui integralmente** os dados e as projeções já carregadas.

As colunas de e-mail na Hierarquia são opcionais: quando presentes, permitem que o app
identifique automaticamente o perfil de quem acessa via login corporativo (Azure/Entra ID).
"""
)

if has_data(conn):
    st.info("Já existem dados carregados no app.")

st.subheader("Ciclo da projeção")
st.caption(
    "A Data Ciclo define o mês de referência da coleta. As colunas de projeção são nomeadas "
    "a partir do mês seguinte a ela. Ex.: Data Ciclo = Jul/26 → colunas Ago/26, Set/26, Out/26..."
)

today = date.today()
default_month = int(get_config(conn, "cycle_month", today.month))
default_year = int(get_config(conn, "cycle_year", today.year))

col_mes, col_ano = st.columns(2)
with col_mes:
    cycle_month = st.selectbox(
        "Mês do ciclo", options=list(range(1, 13)),
        format_func=lambda m: MESES_NOMES[m - 1], index=default_month - 1,
    )
with col_ano:
    cycle_year = st.number_input("Ano do ciclo", min_value=2000, max_value=2100, value=default_year, step=1)

preview_labels = ", ".join(month_label_for_cycle(cycle_year, cycle_month, m) for m in range(1, 7))
st.caption(f"Prévia das colunas de previsão (até 6 meses de horizonte): {preview_labels}, ...")

uploaded = st.file_uploader("Arquivo Excel (.xlsx)", type=["xlsx"])

if uploaded is not None:
    try:
        parsed = parse_workbook(uploaded)
    except ValidationError as e:
        st.error(str(e))
    else:
        st.write("Pré-visualização:")
        tabs = st.tabs(["Hierarquia", "Produtos", "Volumes"])
        with tabs[0]:
            st.dataframe(parsed["hierarchy"].head(20), use_container_width=True)
        with tabs[1]:
            st.dataframe(parsed["products"].head(20), use_container_width=True)
        with tabs[2]:
            st.dataframe(parsed["volumes"].head(20), use_container_width=True)

        if st.button("Confirmar e carregar dados", type="primary"):
            reset_data(conn)
            try:
                stats = load_into_db(conn, parsed, int(cycle_year), int(cycle_month))
            except Exception as e:
                st.error(f"Falha ao carregar dados: {e}")
            else:
                set_config(conn, "cycle_month", cycle_month)
                set_config(conn, "cycle_year", cycle_year)
                st.success(
                    f"Carregado com sucesso: {stats['hierarquia']} vendedores na hierarquia, "
                    f"{stats['produtos']} produtos, {stats['volumes']} linhas de volume, "
                    f"{stats['projecoes']} células de projeção inicializadas."
                )
                st.info("Vá para **Home** para escolher seu perfil e continuar.")
