import pandas as pd
import streamlit as st

from db import init_db, now_iso
from ui_helpers import filter_dataframe, fill_label, fill_caption, apply_theme

apply_theme()
conn = st.session_state.get("conn") or init_db()
st.session_state["conn"] = conn

st.title(":material/assignment: Backlog de Melhorias")
st.caption("Lista de ideias, ajustes e melhorias para o app. Independe da planilha carregada.")

_flash = st.session_state.pop("flash_msg_backlog", None)
if _flash:
    st.success(_flash)

autor_padrao = st.session_state.get("identidade_nome") or ""

PRIORIDADES = ["Alta", "Média", "Baixa"]
STATUSES = ["Pendente", "Em andamento", "Concluído"]
_prioridade_ordem = {"Alta": 0, "Média": 1, "Baixa": 2}
_status_ordem = {"Pendente": 0, "Em andamento": 1, "Concluído": 2}

st.subheader("Adicionar item")
with st.form("novo_item_backlog", clear_on_submit=True):
    titulo = st.text_input("Título")
    descricao = st.text_area("Descrição", height=80)
    col1, col2 = st.columns(2)
    prioridade = col1.selectbox("Prioridade", PRIORIDADES, index=1)
    autor = col2.text_input("Seu nome", value=autor_padrao)
    enviar = st.form_submit_button("Adicionar ao backlog", icon=":material/add:")
    if enviar:
        if not titulo.strip():
            st.error("Informe um título para o item.")
        else:
            conn.execute(
                "INSERT INTO backlog_items (titulo, descricao, prioridade, status, criado_por, criado_em, atualizado_em) "
                "VALUES (?, ?, ?, 'Pendente', ?, ?, ?)",
                (titulo.strip(), descricao.strip(), prioridade, autor.strip() or None, now_iso(), now_iso()),
            )
            conn.commit()
            st.session_state["flash_msg_backlog"] = f"Item \"{titulo.strip()}\" adicionado ao backlog."
            st.rerun()

st.divider()
st.subheader("Itens do backlog")

itens = pd.read_sql_query(
    "SELECT id, titulo, descricao, prioridade, status, criado_por, criado_em FROM backlog_items", conn
)

if itens.empty:
    st.info("Nenhum item no backlog ainda. Use o formulário acima para adicionar o primeiro.")
else:
    itens["_ord_status"] = itens["status"].map(_status_ordem).fillna(9)
    itens["_ord_prio"] = itens["prioridade"].map(_prioridade_ordem).fillna(9)
    itens = itens.sort_values(["_ord_status", "_ord_prio", "criado_em"], ascending=[True, True, False])
    itens = itens.drop(columns=["_ord_status", "_ord_prio"]).reset_index(drop=True)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total", len(itens))
    m2.metric("Pendentes", int((itens["status"] == "Pendente").sum()))
    m3.metric("Em andamento", int((itens["status"] == "Em andamento").sum()))
    m4.metric("Concluídos", int((itens["status"] == "Concluído").sum()))

    display = itens.rename(columns={
        "titulo": "Título", "descricao": "Descrição", "prioridade": "Prioridade",
        "status": "Status", "criado_por": "Criado por", "criado_em": "Criado em",
    })

    st.caption("Altere status/prioridade diretamente na tabela e salve.")
    fill_caption()
    view = filter_dataframe(display, key="filtro_backlog")
    edited = st.data_editor(
        view, use_container_width=True, hide_index=True,
        disabled=[c for c in view.columns if c not in ("Status", "Prioridade")],
        column_config={
            "id": None,
            "Status": st.column_config.SelectboxColumn(fill_label("Status"), options=STATUSES),
            "Prioridade": st.column_config.SelectboxColumn(fill_label("Prioridade"), options=PRIORIDADES),
            "Descrição": st.column_config.TextColumn(width="large"),
        },
        key="backlog_editor",
    )

    if st.button("Salvar alterações", icon=":material/save:", key="save_backlog"):
        cur = conn.cursor()
        n = 0
        for i, row in edited.iterrows():
            original = view.iloc[i]
            if row["Status"] != original["Status"] or row["Prioridade"] != original["Prioridade"]:
                cur.execute(
                    "UPDATE backlog_items SET status = ?, prioridade = ?, atualizado_em = ? WHERE id = ?",
                    (row["Status"], row["Prioridade"], now_iso(), int(row["id"])),
                )
                n += 1
        conn.commit()
        st.session_state["flash_msg_backlog"] = f"{n} item(ns) atualizado(s)."
        st.rerun()
