from datetime import date

import pandas as pd
import streamlit as st

from db import init_db, now_iso, get_config
from models import is_deviation, redistribute_by_last_month, horizon_for_family, month_label_for_cycle
from ui_helpers import fmt_milhar

conn = st.session_state.get("conn") or init_db()
st.session_state["conn"] = conn

st.title("🧑‍💼 Área do Vendedor")

if st.session_state.get("papel") != "Vendedor":
    st.warning("Selecione o perfil **Vendedor** na página Home antes de acessar esta tela.")
    st.stop()

vendedor_codigo = st.session_state["identidade_codigo"]
vendedor_nome = st.session_state["identidade_nome"]
st.caption(f"Carteira de **{vendedor_nome}** ({vendedor_codigo})")

_flash = st.session_state.pop("flash_msg", None)
if _flash:
    st.success(_flash)

carteira = pd.read_sql_query(
    "SELECT chave, cliente_nome, regional_descricao, grupo_descricao, produto_codigo, produto_descricao, "
    "supervisor_nome, media_3m, media_6m, minimo, maximo, ultimo_mes FROM volumes WHERE vendedor_codigo = ?",
    conn, params=(vendedor_codigo,),
)

if carteira.empty:
    st.info("Nenhum cliente/SKU encontrado para este vendedor.")
    st.stop()

supervisor_nome = carteira["supervisor_nome"].iloc[0]
regional_descricao = carteira["regional_descricao"].iloc[0]
cycle_year = int(get_config(conn, "cycle_year", date.today().year))
cycle_month = int(get_config(conn, "cycle_month", date.today().month))
produtos_all = pd.read_sql_query("SELECT DISTINCT produto_codigo, produto_descricao, grupo_descricao FROM raw_products", conn)

status_row = conn.execute(
    "SELECT enviado, enviado_em, status_aprovacao FROM submission_status WHERE level = 'vendedor' AND scope_codigo = ?",
    (vendedor_codigo,),
).fetchone()

col_status, col_send = st.columns([3, 1])
with col_status:
    if status_row and status_row["enviado"]:
        aprovacao = status_row["status_aprovacao"] or "Pendente"
        icone = {"Pendente": "🕓", "Aprovado": "✅", "Reprovado": "❌"}.get(aprovacao, "🕓")
        st.info(
            f"Previsão enviada em **{status_row['enviado_em']}**. "
            f"Status de aprovação do supervisor: {icone} **{aprovacao}**."
        )
    else:
        st.warning("Você ainda não enviou sua previsão para aprovação do supervisor.")
with col_send:
    st.write("")
    if st.button("📤 Enviar previsão", key="enviar_previsao"):
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO submission_status "
            "(level, scope_codigo, scope_nome, parent_scope, enviado, enviado_em, enviado_por, status_aprovacao) "
            "VALUES ('vendedor', ?, ?, ?, 1, ?, ?, 'Pendente') "
            "ON CONFLICT(level, scope_codigo) DO UPDATE SET "
            "enviado = 1, enviado_em = excluded.enviado_em, enviado_por = excluded.enviado_por, "
            "status_aprovacao = 'Pendente', aprovado_por = NULL, aprovado_em = NULL",
            (vendedor_codigo, vendedor_nome, supervisor_nome, now_iso(), vendedor_nome),
        )
        conn.commit()
        st.session_state["flash_msg"] = "Previsão enviada para aprovação do supervisor."
        st.rerun()

proj = pd.read_sql_query(
    "SELECT chave, produto_codigo, month_index, month_label, current_value FROM projection_values",
    conn,
)

# Uma linha por Cliente(chave)/SKU, com os meses do horizonte lado a lado.
proj_all = carteira[["chave", "produto_codigo"]].merge(proj, on=["chave", "produto_codigo"])
month_index_to_label = dict(proj_all[["month_index", "month_label"]].drop_duplicates().values)
label_to_month_index = {v: k for k, v in month_index_to_label.items()}
month_labels_sorted = [month_index_to_label[i] for i in sorted(month_index_to_label)]

st.subheader("Visão por cliente")
st.caption(
    "Clique no cabeçalho de uma coluna para classificar a tabela (ex.: por Último Mês, do maior "
    "para o menor, para revisar primeiro os maiores clientes). Marque a caixinha de uma ou mais "
    "linhas para abrir o detalhe: preencha o total por mês (rateado automaticamente entre os SKUs, "
    "proporcional ao Último Mês de cada um) ou ajuste um SKU específico."
)

cliente_agg_all = carteira.groupby("chave").agg(
    cliente_nome=("cliente_nome", "first"),
    skus=("produto_codigo", "nunique"),
    ultimo_mes=("ultimo_mes", "sum"),
).reset_index().sort_values("cliente_nome")

cliente_month_totals = proj_all.pivot_table(
    index="chave", columns="month_label", values="current_value", aggfunc="sum"
).reindex(columns=month_labels_sorted)

weights_by_key = carteira.set_index(["chave", "produto_codigo"])["ultimo_mes"]

busca = st.text_input("🔍 Filtrar cliente", key="filtro_carteira_cliente", placeholder="Digite o nome do cliente...")

with st.container(border=True):
    total_cols = st.columns([3, 0.8, 1.2] + [1] * len(month_labels_sorted))
    total_cols[0].markdown("**Total geral da carteira**")
    total_cols[1].markdown(f"**{int(cliente_agg_all['skus'].sum())}**")
    total_cols[2].markdown(f"**{fmt_milhar(cliente_agg_all['ultimo_mes'].sum())}**")
    for i, m in enumerate(month_labels_sorted):
        v = cliente_month_totals[m].sum() if m in cliente_month_totals.columns else None
        total_cols[3 + i].markdown(f"**{fmt_milhar(v, 1)}**")
st.caption("O total acima sempre reflete toda a carteira, mesmo com o filtro de cliente aplicado.")

cliente_table = cliente_agg_all.rename(
    columns={"chave": "Chave", "cliente_nome": "Cliente", "skus": "SKUs", "ultimo_mes": "Último Mês"}
).copy()
for m in month_labels_sorted:
    cliente_table[m] = cliente_table["Chave"].map(
        cliente_month_totals[m] if m in cliente_month_totals.columns else {}
    )
cliente_table = cliente_table[["Cliente", "Chave", "SKUs", "Último Mês"] + month_labels_sorted]
if busca:
    cliente_table = cliente_table[cliente_table["Cliente"].str.contains(busca, case=False, na=False)]
cliente_table = cliente_table.reset_index(drop=True)

month_fmt = {m: (lambda v: fmt_milhar(v, 1)) for m in month_labels_sorted}
cliente_table_styled = cliente_table.style.format(
    {"Último Mês": fmt_milhar, **month_fmt}, na_rep="-"
)

evento_tabela = st.dataframe(
    cliente_table_styled,
    use_container_width=True,
    hide_index=True,
    on_select="rerun",
    selection_mode="multi-row",
    key="tabela_clientes_vendedor",
)

selected_positions = evento_tabela.selection.rows
selected_chaves = cliente_table.iloc[selected_positions]["Chave"].tolist() if selected_positions else []

for chave in selected_chaves:
    crow = cliente_agg_all[cliente_agg_all["chave"] == chave].iloc[0]
    cliente_nome = crow["cliente_nome"]
    sub_carteira = carteira[carteira["chave"] == chave]
    sub_proj = proj_all[proj_all["chave"] == chave]
    cliente_months = [m for m in month_labels_sorted if m in sub_proj["month_label"].unique()]

    with st.container(border=True):
        st.markdown(f"#### {cliente_nome} — {chave}")
        st.write("**Total do cliente por mês (kg)** — rateado automaticamente entre os SKUs ao salvar.")
        totals_now = sub_proj.groupby("month_label")["current_value"].sum()
        total_row = {m: round(totals_now.get(m, 0.0), 1) for m in cliente_months}
        total_df = pd.DataFrame([total_row])
        total_col_config = {m: st.column_config.NumberColumn(format="%.1f") for m in cliente_months}

        edited_total = st.data_editor(
            total_df, use_container_width=True, hide_index=True,
            column_config=total_col_config, key=f"total_editor_{chave}",
        )
        if st.button("🔀 Ratear pelo Último Mês e salvar", key=f"rateio_btn_{chave}"):
            ts = now_iso()
            cur = conn.cursor()
            n = 0
            for m in cliente_months:
                novo_total = edited_total.iloc[0][m]
                antigo_total = total_row[m]
                if pd.isna(novo_total) or abs(float(novo_total) - antigo_total) < 1e-9:
                    continue
                month_rows = sub_proj[sub_proj["month_label"] == m]
                rows_for_redist = [
                    {"key": r["produto_codigo"], "weight": weights_by_key.get((chave, r["produto_codigo"]), 0)}
                    for _, r in month_rows.iterrows()
                ]
                new_values, ok = redistribute_by_last_month(rows_for_redist, float(novo_total))
                if not ok:
                    continue
                month_idx = label_to_month_index[m]
                for produto_codigo, new_val in new_values.items():
                    cur.execute(
                        "UPDATE projection_values SET current_value = ?, vendor_value = ?, "
                        "last_changed_level = 'vendedor', last_changed_by = ?, last_changed_at = ? "
                        "WHERE chave = ? AND produto_codigo = ? AND month_index = ?",
                        (new_val, new_val, vendedor_nome, ts, chave, produto_codigo, month_idx),
                    )
                    n += cur.rowcount
            conn.commit()
            st.session_state["flash_msg"] = f"Rateio aplicado para {cliente_nome} ({n} célula(s))."
            st.rerun()

        st.divider()
        st.write("**Detalhe por Família e SKU**")

        sku_pivot = sub_proj.pivot_table(index="produto_codigo", columns="month_label", values="current_value")
        sku_pivot = sku_pivot.reindex(columns=cliente_months)
        sku_raw = sub_carteira.set_index("produto_codigo")[
            ["grupo_descricao", "produto_descricao", "media_3m", "media_6m", "minimo", "maximo", "ultimo_mes"]
        ].join(sku_pivot)
        sku_raw["Desvio"] = sku_raw.apply(
            lambda r: "⚠️" if any(is_deviation(r[m], r["ultimo_mes"]) for m in cliente_months if pd.notna(r[m])) else "",
            axis=1,
        )

        sku_display = sku_raw.reset_index().rename(columns={
            "produto_codigo": "Cód. SKU", "grupo_descricao": "Família", "produto_descricao": "SKU",
            "media_3m": "Média 3M", "media_6m": "Média 6M", "minimo": "Mínimo", "maximo": "Máximo",
            "ultimo_mes": "Último Mês",
        }).sort_values(["Família", "SKU"])
        for _c in ["Média 3M", "Média 6M", "Mínimo", "Máximo", "Último Mês"]:
            sku_display[_c] = sku_display[_c].apply(lambda v: fmt_milhar(v, 1))

        disabled_sku_cols = ["Cód. SKU", "Família", "SKU", "Média 3M", "Média 6M", "Mínimo", "Máximo", "Último Mês", "Desvio"]
        sku_col_config = {m: st.column_config.NumberColumn(format="%.1f") for m in cliente_months}

        edited_sku = st.data_editor(
            sku_display, use_container_width=True, hide_index=True,
            disabled=disabled_sku_cols, column_config=sku_col_config, key=f"sku_editor_{chave}",
        )
        if st.button("💾 Salvar valores por SKU", key=f"save_sku_btn_{chave}"):
            ts = now_iso()
            cur = conn.cursor()
            n = 0
            for _, row in edited_sku.iterrows():
                produto_r = row["Cód. SKU"]
                for m in cliente_months:
                    novo_valor = row[m]
                    if pd.isna(novo_valor):
                        continue
                    month_idx = label_to_month_index[m]
                    cur.execute(
                        "UPDATE projection_values SET current_value = ?, vendor_value = ?, "
                        "last_changed_level = 'vendedor', last_changed_by = ?, last_changed_at = ? "
                        "WHERE chave = ? AND produto_codigo = ? AND month_index = ?",
                        (float(novo_valor), float(novo_valor), vendedor_nome, ts, chave, produto_r, month_idx),
                    )
                    n += cur.rowcount
            conn.commit()
            st.session_state["flash_msg"] = f"Valores por SKU salvos para {cliente_nome} ({n} célula(s))."
            st.rerun()

        st.divider()
        st.write("**Adicionar produto sem histórico de compra**")
        produtos_existentes = set(sub_carteira["produto_codigo"])
        produtos_disponiveis = produtos_all[~produtos_all["produto_codigo"].isin(produtos_existentes)]
        if produtos_disponiveis.empty:
            st.caption("Todos os produtos cadastrados já estão nesta carteira para este cliente.")
        else:
            novo_prod_options = produtos_disponiveis.apply(
                lambda r: f"{r['produto_descricao']} ({r['produto_codigo']})", axis=1
            ).tolist()
            col_novo_prod, col_novo_btn = st.columns([3, 1])
            with col_novo_prod:
                novo_produto_sel = st.selectbox("Produto", novo_prod_options, key=f"novo_produto_{chave}")
            with col_novo_btn:
                st.write("")
                if st.button("➕ Adicionar produto", key=f"add_produto_btn_{chave}"):
                    novo_row = produtos_disponiveis.iloc[novo_prod_options.index(novo_produto_sel)]
                    produto_codigo_novo = novo_row["produto_codigo"]
                    produto_descricao_novo = novo_row["produto_descricao"]
                    grupo_descricao_novo = novo_row["grupo_descricao"]
                    ts = now_iso()
                    cur = conn.cursor()
                    cur.execute(
                        "INSERT OR IGNORE INTO volumes (chave, cliente_nome, regional_descricao, supervisor_nome, "
                        "grupo_descricao, vendedor_codigo, vendedor_nome, produto_codigo, produto_descricao, "
                        "media_6m, media_3m, minimo, maximo, ultimo_mes) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL)",
                        (chave, cliente_nome, regional_descricao, supervisor_nome, grupo_descricao_novo,
                         vendedor_codigo, vendedor_nome, produto_codigo_novo, produto_descricao_novo),
                    )
                    horizon = horizon_for_family(grupo_descricao_novo)
                    proj_rows_novos = [
                        (chave, produto_codigo_novo, m, month_label_for_cycle(cycle_year, cycle_month, m),
                         0.0, 0.0, "vendedor", vendedor_nome, ts)
                        for m in range(1, horizon + 1)
                    ]
                    cur.executemany(
                        "INSERT OR IGNORE INTO projection_values (chave, produto_codigo, month_index, month_label, "
                        "current_value, vendor_value, last_changed_level, last_changed_by, last_changed_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        proj_rows_novos,
                    )
                    conn.commit()
                    st.session_state["flash_msg"] = (
                        f"Produto {produto_descricao_novo} adicionado para {cliente_nome} "
                        f"(sem histórico — preencha os valores manualmente)."
                    )
                    st.rerun()
