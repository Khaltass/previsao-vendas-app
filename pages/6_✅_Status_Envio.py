import pandas as pd
import streamlit as st

from db import init_db, has_data, now_iso
from ui_helpers import filter_dataframe, fmt_milhar, fill_label, fill_caption

conn = st.session_state.get("conn") or init_db()
st.session_state["conn"] = conn

st.title("✅ Status de Envio e Aprovação")

if not has_data(conn):
    st.warning("Nenhuma planilha carregada ainda. Vá até a página **Upload** para carregar os dados.")
    st.stop()

st.caption(
    "Acompanhamento de quais vendedores já enviaram suas previsões e o andamento das "
    "aprovações de supervisores e gerentes regionais."
)

_flash = st.session_state.pop("flash_msg", None)
if _flash:
    st.success(_flash)

papel = st.session_state.get("papel")
identidade = st.session_state.get("identidade_nome")
is_supervisor = papel == "Supervisor"
is_gerente = papel == "Gerente Regional"

if not (is_supervisor or is_gerente):
    st.info(
        "Selecione o perfil **Supervisor** ou **Gerente Regional** na página Home para liberar as "
        "ações de aprovação. Sem um perfil selecionado, o painel é exibido apenas para consulta."
    )

hier = pd.read_sql_query(
    "SELECT DISTINCT vendedor_codigo, vendedor_nome, supervisor_nome, regional_descricao FROM volumes",
    conn,
)
status = pd.read_sql_query(
    "SELECT level, scope_codigo, enviado, enviado_em, enviado_por, status_aprovacao, aprovado_por, aprovado_em "
    "FROM submission_status",
    conn,
)

vend_status = status[status["level"] == "vendedor"].drop(columns="level").rename(columns={"scope_codigo": "vendedor_codigo"})
vend = hier.merge(vend_status, on="vendedor_codigo", how="left")
vend["enviado"] = vend["enviado"].fillna(0).astype(int)
vend["status_aprovacao"] = vend["status_aprovacao"].fillna("Pendente")

if is_supervisor:
    vend = vend[vend["supervisor_nome"] == identidade]
elif is_gerente:
    vend = vend[vend["regional_descricao"] == identidade]

vend = vend.sort_values(["regional_descricao", "supervisor_nome", "vendedor_nome"]).reset_index(drop=True)

sup_agg = vend.groupby(["regional_descricao", "supervisor_nome"]).agg(
    vendedores_total=("vendedor_codigo", "nunique"),
    vendedores_enviados=("enviado", "sum"),
    vendedores_aprovados=("status_aprovacao", lambda s: (s == "Aprovado").sum()),
).reset_index()
sup_status = status[status["level"] == "supervisor"].drop(columns="level").rename(columns={"scope_codigo": "supervisor_nome"})
sup = sup_agg.merge(sup_status, on="supervisor_nome", how="left")
sup["status_aprovacao"] = sup["status_aprovacao"].fillna("Pendente")
sup = sup.sort_values(["regional_descricao", "supervisor_nome"]).reset_index(drop=True)

st.subheader("Resumo")
m1, m2, m3, m4 = st.columns(4)
m1.metric("Vendedores na visão", vend["vendedor_codigo"].nunique())
m2.metric("Já enviaram", int(vend["enviado"].sum()))
m3.metric("Aprovados pelo supervisor", int((vend["status_aprovacao"] == "Aprovado").sum()))
m4.metric("Supervisores aprovados pelo gerente", int((sup["status_aprovacao"] == "Aprovado").sum()))

if is_supervisor and not sup.empty:
    minha_linha = sup[sup["supervisor_nome"] == identidade]
    if not minha_linha.empty:
        st.info(f"Seu status de aprovação perante o Gerente Regional: **{minha_linha.iloc[0]['status_aprovacao']}**")

st.divider()
st.subheader("Envio dos vendedores")

if vend.empty:
    st.info("Nenhum vendedor encontrado nesta visão.")
else:
    vend_display = vend.rename(columns={
        "regional_descricao": "Regional", "supervisor_nome": "Supervisor", "vendedor_nome": "Vendedor",
        "vendedor_codigo": "Cód.", "enviado_em": "Enviado em", "enviado_por": "Enviado por",
        "status_aprovacao": "Status Supervisor", "aprovado_por": "Aprovado por", "aprovado_em": "Aprovado em",
    })
    vend_display["Enviado"] = vend_display["enviado"].map({1: "✅ Sim", 0: "❌ Não"})
    vend_display = vend_display[
        ["Regional", "Supervisor", "Vendedor", "Cód.", "Enviado", "Enviado em",
         "Status Supervisor", "Aprovado por", "Aprovado em"]
    ]

    if is_supervisor:
        st.caption("Marque o status de aprovação de cada vendedor da sua equipe e salve.")
        fill_caption()
        vend_view = filter_dataframe(vend_display, key="filtro_status_vendedor")
        edited_vend = st.data_editor(
            vend_view, use_container_width=True, hide_index=True,
            disabled=[c for c in vend_view.columns if c != "Status Supervisor"],
            column_config={
                "Status Supervisor": st.column_config.SelectboxColumn(
                    fill_label("Status Supervisor"), options=["Pendente", "Aprovado", "Reprovado"]
                ),
            },
            key="status_editor_vendedor",
        )
        if st.button("💾 Salvar aprovações de vendedores", key="save_aprov_vendedor"):
            cur = conn.cursor()
            n = 0
            for i, row in edited_vend.iterrows():
                original = vend_view.iloc[i]
                if row["Status Supervisor"] != original["Status Supervisor"]:
                    cur.execute(
                        "INSERT INTO submission_status "
                        "(level, scope_codigo, scope_nome, parent_scope, status_aprovacao, aprovado_por, aprovado_em) "
                        "VALUES ('vendedor', ?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT(level, scope_codigo) DO UPDATE SET "
                        "status_aprovacao = excluded.status_aprovacao, "
                        "aprovado_por = excluded.aprovado_por, aprovado_em = excluded.aprovado_em",
                        (row["Cód."], row["Vendedor"], row["Supervisor"], row["Status Supervisor"], identidade, now_iso()),
                    )
                    n += 1
            conn.commit()
            st.session_state["flash_msg"] = f"Status de aprovação atualizado para {n} vendedor(es)."
            st.rerun()
    else:
        vend_view = filter_dataframe(vend_display, key="filtro_status_vendedor")
        st.dataframe(vend_view, use_container_width=True, hide_index=True)

if is_gerente:
    st.divider()
    st.subheader("Aprovação dos supervisores")
    st.caption(
        "Marque o status de aprovação de cada supervisor da regional (considere quantos vendedores "
        "da equipe já enviaram e foram aprovados antes de aprovar o supervisor) e salve."
    )
    sup_display = sup.rename(columns={
        "regional_descricao": "Regional", "supervisor_nome": "Supervisor",
        "vendedores_total": "Vendedores (total)", "vendedores_enviados": "Enviaram",
        "vendedores_aprovados": "Aprovados pelo Supervisor",
        "status_aprovacao": "Status Gerente", "aprovado_por": "Aprovado por", "aprovado_em": "Aprovado em",
    })[
        ["Regional", "Supervisor", "Vendedores (total)", "Enviaram", "Aprovados pelo Supervisor",
         "Status Gerente", "Aprovado por", "Aprovado em"]
    ]
    for _c in ["Vendedores (total)", "Enviaram", "Aprovados pelo Supervisor"]:
        sup_display[_c] = sup_display[_c].apply(fmt_milhar)
    fill_caption()
    sup_view = filter_dataframe(sup_display, key="filtro_status_supervisor")
    edited_sup = st.data_editor(
        sup_view, use_container_width=True, hide_index=True,
        disabled=[c for c in sup_view.columns if c != "Status Gerente"],
        column_config={
            "Status Gerente": st.column_config.SelectboxColumn(
                fill_label("Status Gerente"), options=["Pendente", "Aprovado", "Reprovado"]
            ),
        },
        key="status_editor_supervisor",
    )
    if st.button("💾 Salvar aprovações de supervisores", key="save_aprov_supervisor"):
        cur = conn.cursor()
        n = 0
        for i, row in edited_sup.iterrows():
            original = sup_view.iloc[i]
            if row["Status Gerente"] != original["Status Gerente"]:
                cur.execute(
                    "INSERT INTO submission_status "
                    "(level, scope_codigo, scope_nome, parent_scope, status_aprovacao, aprovado_por, aprovado_em) "
                    "VALUES ('supervisor', ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(level, scope_codigo) DO UPDATE SET "
                    "status_aprovacao = excluded.status_aprovacao, "
                    "aprovado_por = excluded.aprovado_por, aprovado_em = excluded.aprovado_em",
                    (row["Supervisor"], row["Supervisor"], row["Regional"], row["Status Gerente"], identidade, now_iso()),
                )
                n += 1
        conn.commit()
        st.session_state["flash_msg"] = f"Status de aprovação atualizado para {n} supervisor(es)."
        st.rerun()
