import io
import pandas as pd
import streamlit as st

from db import init_db, has_data
from models import is_deviation, reference_volume
from ui_helpers import filter_dataframe, fmt_milhar, apply_theme

apply_theme()
conn = st.session_state.get("conn") or init_db()
st.session_state["conn"] = conn

st.title(":material/bar_chart: Consolidação final")

if not has_data(conn):
    st.warning("Nenhuma planilha carregada ainda. Vá até a página **Upload** para carregar os dados.")
    st.stop()

st.caption("Visão consolidada de **todos** os vendedores, supervisores e gerentes regionais.")

volumes = pd.read_sql_query(
    "SELECT chave, cliente_nome, regional_descricao, supervisor_nome, grupo_descricao, "
    "vendedor_codigo, vendedor_nome, produto_codigo, produto_descricao, media_3m, media_6m, ultimo_mes FROM volumes",
    conn,
)
proj = pd.read_sql_query(
    "SELECT chave, produto_codigo, month_index, month_label, current_value FROM projection_values",
    conn,
)

merged = volumes.merge(proj, on=["chave", "produto_codigo"])
merged["Desvio"] = merged.apply(
    lambda r: is_deviation(r["current_value"], reference_volume(r["media_3m"], r["media_6m"])), axis=1
)
month_order_map = dict(merged[["month_label", "month_index"]].drop_duplicates().values)

manual = pd.read_sql_query(
    "SELECT level, scope_name, chave, cliente_nome, produto_codigo, month_label, value FROM manual_adjustments",
    conn,
)
if not manual.empty:
    produtos = pd.read_sql_query("SELECT DISTINCT produto_codigo, produto_descricao, grupo_descricao FROM raw_products", conn)
    manual = manual.merge(produtos, on="produto_codigo", how="left")
    hierarquia_ref = volumes[["chave", "regional_descricao", "supervisor_nome"]].drop_duplicates()
    manual = manual.merge(hierarquia_ref, on="chave", how="left")
    manual["vendedor_nome"] = "(ajuste manual — " + manual["level"] + ": " + manual["scope_name"] + ")"
    manual["Desvio"] = False
    manual = manual.rename(columns={"value": "current_value"})

base_cols = ["regional_descricao", "supervisor_nome", "vendedor_nome", "grupo_descricao",
             "produto_codigo", "produto_descricao", "chave", "cliente_nome", "month_label", "current_value", "Desvio"]
detalhe = merged[base_cols].copy()
if not manual.empty:
    manual_detalhe = manual.reindex(columns=base_cols)
    detalhe = pd.concat([detalhe, manual_detalhe], ignore_index=True)

detalhe_display = detalhe.rename(columns={
    "regional_descricao": "Regional", "supervisor_nome": "Supervisor", "vendedor_nome": "Vendedor",
    "grupo_descricao": "Família", "produto_codigo": "Cód. SKU", "produto_descricao": "SKU",
    "chave": "Chave", "cliente_nome": "Cliente", "month_label": "Mês", "current_value": "Volume (kg)",
})


st.subheader("Totais por mês")
group_by = st.multiselect(
    "Agrupar por", ["Regional", "Supervisor", "Vendedor", "Família", "SKU", "Cliente", "Chave"],
    default=["Família", "SKU"],
)
if group_by:
    # "SKU" sempre traz o código do produto junto com a descrição.
    group_by_cols = []
    for g in group_by:
        group_by_cols.extend(["Cód. SKU", "SKU"] if g == "SKU" else [g])

    totals = detalhe_display.pivot_table(
        index=group_by_cols, columns="Mês", values="Volume (kg)", aggfunc="sum", fill_value=0.0
    )
    month_cols_sorted = sorted(totals.columns, key=lambda m: month_order_map.get(m, 9999))
    totals = totals.reindex(columns=month_cols_sorted)
    totals = totals.reset_index()
    numeric_totais_cols = month_cols_sorted

    totals_view = filter_dataframe(totals, key="filtro_totais")

    total_row = {c: "" for c in totals_view.columns}
    total_row[group_by_cols[0]] = "Total geral"
    for m in numeric_totais_cols:
        total_row[m] = totals_view[m].sum()
    totals_display = pd.concat([totals_view, pd.DataFrame([total_row])], ignore_index=True)

    st.dataframe(
        totals_display.style.format({c: fmt_milhar for c in numeric_totais_cols}, na_rep="-"),
        use_container_width=True, hide_index=True,
    )

st.divider()
st.subheader("Detalhe por Regional")
st.caption(":material/add: para abrir uma regional e ver o detalhamento por Família de produto e SKU.")

regional_agg = detalhe_display.groupby("Regional")["Volume (kg)"].sum().reset_index().sort_values("Regional")

busca_regional = st.text_input(
    "Filtrar regional", key="filtro_regional_detalhe", placeholder="Digite o nome da regional...",
    icon=":material/search:",
)
if busca_regional:
    regional_agg = regional_agg[regional_agg["Regional"].str.contains(busca_regional, case=False, na=False)]

col_widths_regional = [0.6, 3, 2]
header_cols = st.columns(col_widths_regional)
header_cols[1].markdown("**Regional**")
header_cols[2].markdown("**Total (kg)**")

for _, rrow in regional_agg.iterrows():
    regional = rrow["Regional"]
    exp_key = f"expand_regional_{regional}"
    aberto = st.session_state.get(exp_key, False)

    with st.container(border=True):
        row_cols = st.columns(col_widths_regional)
        toggle_icon = ":material/remove:" if aberto else ":material/add:"
        if row_cols[0].button("", icon=toggle_icon, key=f"toggle_regional_{regional}"):
            st.session_state[exp_key] = not aberto
            st.rerun()
        row_cols[1].write(regional)
        row_cols[2].write(fmt_milhar(rrow["Volume (kg)"]))

        if not aberto:
            continue

        st.divider()
        sub_regional = detalhe_display[detalhe_display["Regional"] == regional]
        view_by_regional = st.radio(
            "Visualizar por", ["Família", "SKU"], horizontal=True, key=f"viewby_regional_{regional}"
        )
        group_col_regional = ["Cód. SKU", "SKU"] if view_by_regional == "SKU" else [view_by_regional]

        pivot_regional = sub_regional.pivot_table(
            index=group_col_regional, columns="Mês", values="Volume (kg)", aggfunc="sum", fill_value=0.0
        )
        month_cols_regional = sorted(pivot_regional.columns, key=lambda m: month_order_map.get(m, 9999))
        pivot_regional = pivot_regional.reindex(columns=month_cols_regional).reset_index()

        total_row_regional = {c: "" for c in pivot_regional.columns}
        total_row_regional[group_col_regional[0]] = "Total geral"
        for m in month_cols_regional:
            total_row_regional[m] = pivot_regional[m].sum()
        pivot_regional_display = pd.concat([pivot_regional, pd.DataFrame([total_row_regional])], ignore_index=True)

        st.dataframe(
            pivot_regional_display.style.format({c: fmt_milhar for c in month_cols_regional}, na_rep="-"),
            use_container_width=True, hide_index=True,
        )

st.divider()
st.subheader("Exportar")

csv_bytes = detalhe_display.to_csv(index=False).encode("utf-8-sig")
st.download_button(
    "Baixar CSV", data=csv_bytes, file_name="consolidacao_vendas.csv", mime="text/csv",
    icon=":material/download:",
)

xlsx_buffer = io.BytesIO()
with pd.ExcelWriter(xlsx_buffer, engine="xlsxwriter") as writer:
    detalhe_display.to_excel(writer, index=False, sheet_name="Consolidacao")
    if group_by:
        export_total_row = {c: "" for c in totals.columns}
        export_total_row[group_by_cols[0]] = "Total geral"
        for m in numeric_totais_cols:
            export_total_row[m] = totals[m].sum()
        totals_export = pd.concat([totals, pd.DataFrame([export_total_row])], ignore_index=True)
        totals_export.to_excel(writer, index=False, sheet_name="Totais")
st.download_button(
    "Baixar Excel", data=xlsx_buffer.getvalue(),
    file_name="consolidacao_vendas.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    icon=":material/download:",
)
