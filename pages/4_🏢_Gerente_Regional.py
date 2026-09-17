import pandas as pd
import streamlit as st

from db import init_db, now_iso
from models import is_deviation, reference_volume, redistribute_proportional
from ui_helpers import filter_dataframe, fmt_milhar, fill_label, fill_caption, apply_theme

apply_theme()
conn = st.session_state.get("conn") or init_db()
st.session_state["conn"] = conn

st.title(":material/corporate_fare: Área do Gerente Regional")

if st.session_state.get("papel") != "Gerente Regional":
    st.warning("Selecione o perfil **Gerente Regional** na página Home antes de acessar esta tela.")
    st.stop()

regional = st.session_state["identidade_nome"]
st.caption(f"Consolidação da regional **{regional}** (todos os supervisores)")

_flash = st.session_state.pop("flash_msg", None)
if _flash:
    st.success(_flash)

volumes = pd.read_sql_query(
    "SELECT chave, cliente_nome, grupo_descricao, produto_codigo, produto_descricao, "
    "supervisor_nome, vendedor_codigo, vendedor_nome, media_3m, media_6m, minimo, maximo, ultimo_mes "
    "FROM volumes WHERE regional_descricao = ?",
    conn, params=(regional,),
)
if volumes.empty:
    st.info("Nenhum dado encontrado para esta regional.")
    st.stop()

st.subheader("Validação dos supervisores")

sup_status = pd.read_sql_query(
    "SELECT scope_codigo AS supervisor_nome, enviado, enviado_em "
    "FROM submission_status WHERE level = 'supervisor'",
    conn,
)
supervisores = volumes[["supervisor_nome"]].drop_duplicates().sort_values("supervisor_nome")
supervisores = supervisores.merge(sup_status, on="supervisor_nome", how="left")
supervisores["enviado"] = supervisores["enviado"].fillna(0).astype(int)

total_sup = len(supervisores)
validaram_sup = int(supervisores["enviado"].sum())

st.metric("Supervisores que já validaram", f"{validaram_sup} de {total_sup}")
sup_display = supervisores.rename(columns={"supervisor_nome": "Supervisor", "enviado_em": "Validado em"})
sup_display["Validado"] = sup_display["enviado"].map({1: "Sim", 0: "Não"})
st.dataframe(
    sup_display[["Supervisor", "Validado", "Validado em"]],
    use_container_width=True, hide_index=True,
)

st.divider()

proj = pd.read_sql_query(
    "SELECT chave, produto_codigo, month_index, month_label, current_value, vendor_value, last_changed_level "
    "FROM projection_values",
    conn,
)

merged = volumes.merge(proj, on=["chave", "produto_codigo"])
merged["Desvio"] = merged.apply(
    lambda r: is_deviation(r["current_value"], reference_volume(r["media_3m"], r["media_6m"])), axis=1
)
# só entra na revisão de desvios quem ainda não foi corrigido por supervisor/gerente
merged["_pendente"] = merged["Desvio"] & (merged["last_changed_level"] == "vendedor")

st.subheader("Consolidação")
view_by = st.radio("Visualizar por", ["Família", "SKU", "Supervisor"], horizontal=True)
group_col = {"Família": "grupo_descricao", "SKU": "produto_descricao", "Supervisor": "supervisor_nome"}[view_by]

pivot = merged.pivot_table(
    index=group_col, columns="month_label", values="current_value", aggfunc="sum", fill_value=0
)
month_order = merged.sort_values("month_index")["month_label"].unique().tolist()
pivot = pivot.reindex(columns=[m for m in month_order if m in pivot.columns])

medias_agg = merged.drop_duplicates(subset=["chave", "produto_codigo"]).groupby(group_col)[
    ["media_3m", "media_6m", "minimo", "maximo", "ultimo_mes"]
].sum(min_count=1).rename(columns={
    "media_3m": "Média 3M", "media_6m": "Média 6M", "minimo": "Mínimo", "maximo": "Máximo", "ultimo_mes": "Último Mês",
})

combined = medias_agg.join(pivot).reset_index()
numeric_cols = [c for c in combined.columns if c != group_col]
combined = filter_dataframe(combined, key="filtro_consolidacao")

total_row = {c: "" for c in combined.columns}
total_row[group_col] = "Total geral"
for c in numeric_cols:
    total_row[c] = combined[c].sum()
combined_display = pd.concat([combined, pd.DataFrame([total_row])], ignore_index=True)

st.dataframe(
    combined_display.style.format({c: fmt_milhar for c in numeric_cols}, na_rep="-"),
    use_container_width=True, hide_index=True,
)

st.divider()


def log_audit(cur, chave, produto_codigo, month_index, old_value, new_value):
    cur.execute(
        "INSERT INTO audit_log (chave, produto_codigo, month_index, changed_by_role, changed_by_name, "
        "old_value, new_value, changed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (chave, produto_codigo, month_index, "Gerente Regional", regional, old_value, new_value, now_iso()),
    )


st.subheader("Revisão de desvios")

flagged_keys = merged.loc[merged["_pendente"], ["chave", "produto_codigo"]].drop_duplicates()
if flagged_keys.empty:
    st.success("Nenhum desvio pendente de revisão nesta regional.")
else:
    flagged_keys = flagged_keys.assign(_flag=True)
    desvio_data = merged.merge(flagged_keys, on=["chave", "produto_codigo"], how="inner")

    info = desvio_data.drop_duplicates(subset=["chave", "produto_codigo"]).set_index(["chave", "produto_codigo"])[
        ["supervisor_nome", "cliente_nome", "vendedor_nome", "grupo_descricao", "produto_descricao",
         "media_3m", "media_6m", "minimo", "maximo", "ultimo_mes"]
    ]
    pivot_desvio = desvio_data.pivot_table(index=["chave", "produto_codigo"], columns="month_label", values="current_value")
    pivot_desvio = pivot_desvio.reindex(columns=[m for m in month_order if m in pivot_desvio.columns])
    month_cols = [m for m in month_order if m in pivot_desvio.columns]

    table_desvio = info.join(pivot_desvio).reset_index()
    month_idx_map = desvio_data.drop_duplicates(subset=["chave", "produto_codigo", "month_label"]).set_index(
        ["chave", "produto_codigo", "month_label"]
    )["month_index"].to_dict()

    table_display = table_desvio.rename(columns={
        "chave": "Chave", "supervisor_nome": "Supervisor", "cliente_nome": "Cliente", "vendedor_nome": "Vendedor",
        "grupo_descricao": "Família", "produto_codigo": "Cód. SKU", "produto_descricao": "SKU",
        "media_3m": "Média 3M", "media_6m": "Média 6M", "minimo": "Mínimo", "maximo": "Máximo",
        "ultimo_mes": "Último Mês",
    })
    for _c in ["Média 3M", "Média 6M", "Mínimo", "Máximo", "Último Mês"]:
        table_display[_c] = table_display[_c].apply(lambda v: fmt_milhar(v, 1))
    disabled_cols = [c for c in table_display.columns if c not in month_cols]
    desvio_column_config = {m: st.column_config.NumberColumn(fill_label(m), format="%.1f") for m in month_cols}

    st.caption(f"{len(table_display)} linha(s) com projeção mais de 10% abaixo da Média 3M (ou 6M, na ausência da 3M). Edite diretamente na tabela para revisar linha a linha.")
    fill_caption()
    table_display = filter_dataframe(table_display, key="filtro_desvios_regional")
    with st.form(key="desvio_form_regional"):
        edited_desvio = st.data_editor(
            table_display, use_container_width=True, hide_index=True,
            disabled=disabled_cols, column_config=desvio_column_config, key="desvio_editor_regional",
        )
        desvio_save_submitted = st.form_submit_button("Salvar revisão manual", icon=":material/save:")
    if desvio_save_submitted:
        cur = conn.cursor()
        n = 0
        for i, row in edited_desvio.iterrows():
            original = table_display.iloc[i]
            chave_r, produto_r = row["Chave"], row["Cód. SKU"]
            for m in month_cols:
                key = (chave_r, produto_r, m)
                if key not in month_idx_map:
                    continue
                novo, antigo = row[m], original[m]
                if pd.notna(novo) and (pd.isna(antigo) or float(novo) != float(antigo)):
                    month_idx = month_idx_map[key]
                    cur.execute(
                        "UPDATE projection_values SET current_value = ?, last_changed_level = 'gerente_regional', "
                        "last_changed_by = ?, last_changed_at = ? WHERE chave = ? AND produto_codigo = ? AND month_index = ?",
                        (float(novo), regional, now_iso(), chave_r, produto_r, month_idx),
                    )
                    log_audit(cur, chave_r, produto_r, month_idx, antigo, float(novo))
                    n += 1
        conn.commit()
        st.session_state["flash_msg"] = f"Revisão manual salva ({n} célula(s) alterada(s))."
        st.rerun()

    col_b, col_c = st.columns(2)
    with col_b:
        if st.button("Corrigir automaticamente com Média 3M", icon=":material/build:", key="desvio_autofix"):
            cur = conn.cursor()
            n = 0
            for _, row in table_desvio.iterrows():
                media3 = row["media_3m"]
                if pd.isna(media3):
                    continue
                referencia = reference_volume(row["media_3m"], row["media_6m"])
                for m in month_cols:
                    key = (row["chave"], row["produto_codigo"], m)
                    if key not in month_idx_map:
                        continue
                    antigo = row[m]
                    if not is_deviation(antigo, referencia):
                        continue
                    month_idx = month_idx_map[key]
                    mudou = pd.isna(antigo) or float(antigo) != float(media3)
                    cur.execute(
                        "UPDATE projection_values SET current_value = ?, last_changed_level = 'gerente_regional', "
                        "last_changed_by = ?, last_changed_at = ? WHERE chave = ? AND produto_codigo = ? AND month_index = ?",
                        (float(media3), regional, now_iso(), row["chave"], row["produto_codigo"], month_idx),
                    )
                    if mudou:
                        log_audit(cur, row["chave"], row["produto_codigo"], month_idx, antigo, float(media3))
                        n += 1
            conn.commit()
            st.session_state["flash_msg"] = f"Correção automática aplicada com Média 3M ({n} célula(s))."
            st.rerun()
    with col_c:
        if st.button("Corrigir automaticamente com Último Mês", icon=":material/build:", key="desvio_autofix_ultimo"):
            cur = conn.cursor()
            n = 0
            for _, row in table_desvio.iterrows():
                ultimo = row["ultimo_mes"]
                if pd.isna(ultimo):
                    continue
                referencia = reference_volume(row["media_3m"], row["media_6m"])
                for m in month_cols:
                    key = (row["chave"], row["produto_codigo"], m)
                    if key not in month_idx_map:
                        continue
                    antigo = row[m]
                    if not is_deviation(antigo, referencia):
                        continue
                    month_idx = month_idx_map[key]
                    mudou = pd.isna(antigo) or float(antigo) != float(ultimo)
                    cur.execute(
                        "UPDATE projection_values SET current_value = ?, last_changed_level = 'gerente_regional', "
                        "last_changed_by = ?, last_changed_at = ? WHERE chave = ? AND produto_codigo = ? AND month_index = ?",
                        (float(ultimo), regional, now_iso(), row["chave"], row["produto_codigo"], month_idx),
                    )
                    if mudou:
                        log_audit(cur, row["chave"], row["produto_codigo"], month_idx, antigo, float(ultimo))
                        n += 1
            conn.commit()
            st.session_state["flash_msg"] = f"Correção automática aplicada com Último Mês ({n} célula(s))."
            st.rerun()

st.divider()

tab1, tab2, tab3 = st.tabs([
    "Editar célula específica",
    "Ajustar total por grupo (redistribuição proporcional)",
    "Ajuste manual (sem projeção prévia)",
])

with tab1:
    st.caption("Ajusta o volume já alocado para um cliente/SKU/mês específico.")
    # "Cliente" é identificado por chave: o mesmo nome pode ter várias filiais/CNPJs distintos.
    clientes_df = volumes[["chave", "cliente_nome"]].drop_duplicates().sort_values("cliente_nome")
    cliente_options = clientes_df.apply(lambda r: f"{r['cliente_nome']} — {r['chave']}", axis=1).tolist()
    cliente_sel = st.selectbox("Cliente", cliente_options, key="t1_cliente")
    chave_sel = clientes_df.iloc[cliente_options.index(cliente_sel)]["chave"]
    sub = volumes[volumes["chave"] == chave_sel]
    sku_options = sub.apply(lambda r: f"{r['produto_descricao']} ({r['produto_codigo']})", axis=1).tolist()
    sku_sel = st.selectbox("SKU", sku_options, key="t1_sku")
    row = sub.iloc[sku_options.index(sku_sel)]
    grid = proj[(proj["chave"] == row["chave"]) & (proj["produto_codigo"] == row["produto_codigo"])].sort_values("month_index")
    mes_sel = st.selectbox("Mês", grid["month_label"].tolist(), key="t1_mes")
    grid_row = grid[grid["month_label"] == mes_sel].iloc[0]
    st.metric("Valor atual", f"{grid_row['current_value']:.0f} kg")
    novo_valor = st.number_input(fill_label("Novo valor (kg)"), min_value=0.0, value=float(grid_row["current_value"]), key="t1_valor")
    if st.button("Aplicar ajuste", key="t1_apply"):
        cur = conn.cursor()
        cur.execute(
            "UPDATE projection_values SET current_value = ?, last_changed_level = 'gerente_regional', "
            "last_changed_by = ?, last_changed_at = ? WHERE chave = ? AND produto_codigo = ? AND month_index = ?",
            (novo_valor, regional, now_iso(), row["chave"], row["produto_codigo"], grid_row["month_index"]),
        )
        log_audit(cur, row["chave"], row["produto_codigo"], grid_row["month_index"], grid_row["current_value"], novo_valor)
        conn.commit()
        st.session_state["flash_msg"] = "Ajuste aplicado e registrado na auditoria."
        st.rerun()

with tab2:
    st.caption(
        "Redistribui um novo total entre os supervisores/clientes proporcionalmente ao volume já alocado."
    )
    scope_col = {"Família": "grupo_descricao", "SKU": "produto_descricao", "Supervisor": "supervisor_nome"}[view_by]
    scope_options = sorted(merged[scope_col].unique())
    scope_sel = st.selectbox(f"{view_by}", scope_options, key="t2_scope")
    mes_sel2 = st.selectbox("Mês", month_order, key="t2_mes")

    scope_rows = merged[(merged[scope_col] == scope_sel) & (merged["month_label"] == mes_sel2)]
    total_atual = scope_rows["current_value"].sum()
    st.metric(f"Total atual alocado em {mes_sel2}", f"{total_atual:.0f} kg")

    novo_total = st.number_input(fill_label("Novo total (kg)"), min_value=0.0, value=float(total_atual), key="t2_total")
    if st.button("Redistribuir proporcionalmente", key="t2_apply"):
        rows_for_redist = [
            {"key": (r["chave"], r["produto_codigo"], r["month_index"]), "value": r["current_value"]}
            for _, r in scope_rows.iterrows()
        ]
        new_values, ok = redistribute_proportional(rows_for_redist, novo_total)
        if not ok:
            st.error(
                "Não há volume já alocado nesse grupo/mês para redistribuir proporcionalmente. "
                "Use a aba **Ajuste manual** para incluir um novo cliente/SKU."
            )
        else:
            cur = conn.cursor()
            old_by_key = {r["key"]: r["value"] for r in rows_for_redist}
            for key, new_val in new_values.items():
                chave, produto_codigo, month_index = key
                cur.execute(
                    "UPDATE projection_values SET current_value = ?, last_changed_level = 'gerente_regional', "
                    "last_changed_by = ?, last_changed_at = ? WHERE chave = ? AND produto_codigo = ? AND month_index = ?",
                    (new_val, regional, now_iso(), chave, produto_codigo, month_index),
                )
                log_audit(cur, chave, produto_codigo, month_index, old_by_key[key], new_val)
            conn.commit()
            st.session_state["flash_msg"] = f"Redistribuído entre {len(new_values)} linha(s) e registrado na auditoria."
            st.rerun()

with tab3:
    st.caption("Inclui volume para um cliente/SKU que nenhum vendedor projetou (sem base para redistribuição).")
    with st.form("manual_adjustment_form_regional"):
        cliente_manual = st.text_input("Nome do cliente")
        produtos = pd.read_sql_query("SELECT DISTINCT produto_codigo, produto_descricao FROM raw_products", conn)
        prod_options = produtos.apply(lambda r: f"{r['produto_descricao']} ({r['produto_codigo']})", axis=1).tolist()
        produto_manual = st.selectbox("SKU", prod_options) if prod_options else None
        mes_manual = st.selectbox("Mês", month_order, key="t3_mes")
        valor_manual = st.number_input(fill_label("Valor (kg)"), min_value=0.0, value=0.0, key="t3_valor")
        nota_manual = st.text_area("Nota / justificativa")
        submitted = st.form_submit_button("Adicionar ajuste manual")
        if submitted:
            if not cliente_manual or produto_manual is None:
                st.error("Informe o cliente e o SKU.")
            else:
                produto_codigo_manual = produto_manual.split("(")[-1].rstrip(")")
                chave_manual = f"MANUAL-{cliente_manual}-{produto_codigo_manual}"
                month_index_manual = month_order.index(mes_manual) + 1
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO manual_adjustments (level, scope_name, chave, cliente_nome, produto_codigo, "
                    "month_index, month_label, value, created_by, created_at, note) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    ("gerente_regional", regional, chave_manual, cliente_manual, produto_codigo_manual,
                     month_index_manual, mes_manual, valor_manual, regional, now_iso(), nota_manual),
                )
                conn.commit()
                st.session_state["flash_msg"] = "Ajuste manual registrado."
                st.rerun()

    existentes = pd.read_sql_query(
        "SELECT cliente_nome, produto_codigo, month_label, value, created_by, created_at, note "
        "FROM manual_adjustments WHERE level = 'gerente_regional' AND scope_name = ?",
        conn, params=(regional,),
    )
    if not existentes.empty:
        st.write("Ajustes manuais já registrados:")
        existentes = filter_dataframe(existentes, key="filtro_ajustes_manuais_regional")
        st.dataframe(
            existentes.style.format({"value": lambda v: fmt_milhar(v, 1)}, na_rep="-"),
            use_container_width=True, hide_index=True,
        )
