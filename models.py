"""Regras de negócio puras: horizonte por família, desvio, redistribuição proporcional."""
import unicodedata

DEFAULT_HORIZON = 3

_HORIZON_BY_FAMILY = {
    "parmesao": 6,
    "gouda": 4,
}

DEVIATION_THRESHOLD = 0.9

MESES_ABREV = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]


def month_label_for_cycle(cycle_year: int, cycle_month: int, offset: int) -> str:
    """Rótulo abreviado (ex: 'Ago/26') do mês `offset` posições após o ciclo (mês/ano) informado.

    `offset=1` é o primeiro mês de projeção, ou seja, o mês seguinte ao ciclo.
    """
    total = cycle_year * 12 + (cycle_month - 1) + offset
    year, month0 = divmod(total, 12)
    return f"{MESES_ABREV[month0]}/{year % 100:02d}"


def _normalize(text: str) -> str:
    if text is None:
        return ""
    text = unicodedata.normalize("NFKD", str(text))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.strip().lower()


def horizon_for_family(grupo_descricao: str) -> int:
    """Retorna o horizonte de projeção (em meses) para uma família de produto.

    Usa correspondência por substring (não igualdade exata) porque a
    descrição do grupo na base real combina nomes, ex: "MONTANHES / PARMESAO"
    ou "QUEIJO GOUDA", não apenas "Parmesão"/"Gouda" isolados.
    """
    normalized = _normalize(grupo_descricao)
    for keyword, horizon in _HORIZON_BY_FAMILY.items():
        if keyword in normalized:
            return horizon
    return DEFAULT_HORIZON


def fmt_kg(value) -> str:
    """Formata um volume em kg para exibição, tratando ausência de dado (None/NaN)."""
    if value is None:
        return "-"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "-"
    if value != value:  # NaN
        return "-"
    return f"{value:.0f} kg"


def is_deviation(projected, ultimo_mes) -> bool:
    """True quando o volume projetado é mais de 10% inferior ao último mês realizado."""
    if projected is None or ultimo_mes is None:
        return False
    try:
        projected = float(projected)
        ultimo_mes = float(ultimo_mes)
    except (TypeError, ValueError):
        return False
    if ultimo_mes <= 0:
        return False
    return projected < DEVIATION_THRESHOLD * ultimo_mes


def _safe_num(value) -> float:
    """Converte None/NaN/valores inválidos para 0.0. `value or 0` não é suficiente porque
    NaN é "truthy" em Python (NaN or 0 == NaN), o que propagaria NaN pelo rateio inteiro."""
    if value is None:
        return 0.0
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if value != value else value  # value != value só é True para NaN


def redistribute_by_last_month(rows, new_total):
    """Redistribui `new_total` entre `rows` (lista de dicts com 'key' e 'weight'),
    proporcionalmente ao peso de cada linha (tipicamente o Último Mês realizado do SKU).

    Retorna (novos_valores: dict[key, float], redistributable: bool).
    Quando nenhuma linha tem peso (todas 0/None), distribui igualmente entre as linhas
    em vez de bloquear o rateio — no nível do vendedor não faz sentido exigir ajuste manual.
    """
    if not rows:
        return {}, False
    weights = [_safe_num(r["weight"]) for r in rows]
    total_weight = sum(weights)
    if total_weight <= 0:
        equal = new_total / len(rows)
        return {r["key"]: equal for r in rows}, True
    return {r["key"]: new_total * (w / total_weight) for r, w in zip(rows, weights)}, True


def redistribute_proportional(rows, new_total):
    """Redistribui `new_total` entre `rows` (lista de dicts com 'key' e 'value'),
    proporcionalmente ao volume já alocado em cada linha.

    Retorna (novos_valores: dict[key, float], redistributable: bool).
    Quando o total atual é 0 (nenhum vendedor alocou nada), não há base
    proporcional e a chamada deve ser tratada como ajuste manual (seção 6).
    """
    values = [_safe_num(r["value"]) for r in rows]
    old_total = sum(values)
    if old_total <= 0:
        return {}, False
    scale = new_total / old_total
    return {r["key"]: v * scale for r, v in zip(rows, values)}, True
