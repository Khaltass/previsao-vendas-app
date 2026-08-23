"""Helpers de UI reutilizados pelas páginas do app."""
import streamlit as st

# Sem seletor de variação (VS16): renderiza como traço monocromático, não como
# emoji colorido — necessário porque este ícone também aparece em cabeçalhos de
# coluna de data_editor (grade em canvas, onde ":material/..." não é suportado).
FILL_ICON = "✏"


def apply_theme():
    """CSS complementar ao tema visual (.streamlit/config.toml), para ajustes finos
    que o tema sozinho não cobre. Chamado no topo de cada página, já que o Streamlit
    reexecuta o script inteiro a cada navegação."""
    st.markdown(
        """
        <style>
        [data-testid="stMetricValue"] { font-weight: 600; }
        [data-testid="stMetricLabel"] {
            text-transform: uppercase;
            letter-spacing: 0.04em;
            font-size: 0.78rem;
            color: #5B6270;
        }
        div[data-testid="stAlert"] { border-radius: 6px; }
        section[data-testid="stSidebar"] { border-right: 1px solid #E2E4E9; }
        div.stButton > button, div.stDownloadButton > button {
            transition: filter 0.15s ease;
        }
        div.stButton > button:hover, div.stDownloadButton > button:hover {
            filter: brightness(0.93);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def fill_label(text: str) -> str:
    """Prefixa o rótulo de uma coluna/campo editável com um ícone, para destacar
    visualmente (Streamlit não permite colorir células de data_editor por coluna)."""
    return f"{FILL_ICON} {text}"


def fill_caption():
    st.caption(":material/edit: indica colunas e campos abertos para preenchimento/edição.")


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


def filter_dataframe(df, key, label="Filtrar tabela"):
    """Campo de texto que filtra as linhas do dataframe por qualquer coluna (case-insensitive).

    Sempre reindexa (0..n-1) o resultado, já que várias telas alinham edições
    de volta ao dataframe original por posição (.iloc) após a filtragem.
    """
    query = st.text_input(
        label, key=key, placeholder="Digite para filtrar por qualquer coluna...", icon=":material/search:"
    )
    if not query:
        return df.reset_index(drop=True)
    mask = df.astype(str).apply(lambda col: col.str.contains(query, case=False, na=False, regex=False))
    return df[mask.any(axis=1)].reset_index(drop=True)
