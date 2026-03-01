"""
lake_loader.py — Lê catalog.db e agrega métricas por (ativo, hh_mm, direcao)

LÓGICA:
- Para cada (ativo, hh_mm, direcao), conta wins e hits nas janelas de 30/7/3 dias
- A direção dominante é determinada por qual direção tem mais wins na primeira entrada
- Retorna DataFrame pronto para o uploader

NÃO modifica nenhum arquivo existente.
Lê apenas: catalog/catalog.db
"""

import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta

ATIVOS = ["R_10", "R_25", "R_50", "R_75", "R_100"]
# Caminho absoluto relativo à raiz do projeto (funciona de qualquer diretório)
DB_PATH = Path(__file__).parent.parent / "catalog" / "catalog.db"

# Janelas de tempo em dias
JANELA_30D = 30
JANELA_7D = 7
JANELA_3D = 3


def get_epoch_corte(dias: int) -> int:
    """Retorna epoch UTC do início da janela (dias atrás)."""
    corte = datetime.utcnow() - timedelta(days=dias)
    return int(corte.timestamp())


def load_catalog(ativo: str) -> pd.DataFrame:
    """Carrega velas do catalog.db para um ativo específico."""
    conn = sqlite3.connect(DB_PATH)
    # Tabela real: candles | colunas: proxima_1/2/3 com "VERDE"/"VERMELHA"/"?"
    query = """
        SELECT
            timestamp,
            hh_mm,
            proxima_1,
            proxima_2,
            proxima_3
        FROM candles
        WHERE ativo = ?
        ORDER BY timestamp ASC
    """
    df = pd.read_sql_query(query, conn, params=(ativo,))
    conn.close()
    return df


def calcular_metricas_janela(df: pd.DataFrame, epoch_corte: int, direcao: str) -> dict:
    """
    Calcula win_1a, win_g1, win_g2 e n_hit para uma janela de tempo e direção.

    direcao="CALL" → cor_alvo="VERDE"
    direcao="PUT"  → cor_alvo="VERMELHA"
    Ciclos completos = proxima_3 != "?" (todas as 3 velas futuras conhecidas)
    """
    cor_alvo = "VERDE" if direcao == "CALL" else "VERMELHA"
    df_janela = df[df["timestamp"] >= epoch_corte].copy()

    if df_janela.empty:
        return {"n": 0, "win_1a": 0, "win_g1": 0, "win_g2": 0, "hit": 0}

    # Ciclos completos apenas (proxima_3 != "?" garante que as 3 velas existem)
    df_completo = df_janela[df_janela["proxima_3"] != "?"]
    n = len(df_completo)

    if n == 0:
        return {"n": 0, "win_1a": 0, "win_g1": 0, "win_g2": 0, "hit": 0}

    win_1a = (df_completo["proxima_1"] == cor_alvo).sum()
    win_g1 = ((df_completo["proxima_1"] != cor_alvo) &
               (df_completo["proxima_2"] == cor_alvo)).sum()
    win_g2 = ((df_completo["proxima_1"] != cor_alvo) &
               (df_completo["proxima_2"] != cor_alvo) &
               (df_completo["proxima_3"] == cor_alvo)).sum()
    hit = ((df_completo["proxima_1"] != cor_alvo) &
            (df_completo["proxima_2"] != cor_alvo) &
            (df_completo["proxima_3"] != cor_alvo)).sum()

    # Invariante: win_1a + win_g1 + win_g2 + hit == n
    assert int(win_1a + win_g1 + win_g2 + hit) == n, \
        f"INVARIANTE QUEBRADA: {win_1a}+{win_g1}+{win_g2}+{hit} != {n}"

    return {
        "n": int(n),
        "win_1a": int(win_1a),
        "win_g1": int(win_g1),
        "win_g2": int(win_g2),
        "hit": int(hit),
    }


def agregar_ativo(ativo: str) -> list[dict]:
    """
    Para um ativo, agrega métricas de todos os 1.440 minutos × 2 direções.
    Retorna lista de dicts prontos para INSERT no Supabase.
    """
    print(f"[LOADER] Processando {ativo}...")
    df = load_catalog(ativo)

    if df.empty:
        print(f"[LOADER] ⚠️  Nenhum dado para {ativo}")
        return []

    epoch_30d = get_epoch_corte(JANELA_30D)
    epoch_7d  = get_epoch_corte(JANELA_7D)
    epoch_3d  = get_epoch_corte(JANELA_3D)

    resultados = []
    hh_mms = df["hh_mm"].unique()
    total = len(hh_mms)

    for i, hh_mm in enumerate(sorted(hh_mms), 1):
        df_minuto = df[df["hh_mm"] == hh_mm]

        for direcao in ["CALL", "PUT"]:
            m30 = calcular_metricas_janela(df_minuto, epoch_30d, direcao)
            m7  = calcular_metricas_janela(df_minuto, epoch_7d, direcao)
            m3  = calcular_metricas_janela(df_minuto, epoch_3d, direcao)

            resultados.append({
                "ativo":       ativo,
                "hh_mm":       hh_mm,
                "direcao":     direcao,
                "n_30d":       m30["n"],
                "win_1a_30d":  m30["win_1a"],
                "win_g1_30d":  m30["win_g1"],
                "win_g2_30d":  m30["win_g2"],
                "hit_30d":     m30["hit"],
                "n_7d":        m7["n"],
                "win_1a_7d":   m7["win_1a"],
                "win_g1_7d":   m7["win_g1"],
                "win_g2_7d":   m7["win_g2"],
                "hit_7d":      m7["hit"],
                "n_3d":        m3["n"],
                "win_1a_3d":   m3["win_1a"],
                "win_g1_3d":   m3["win_g1"],
                "win_g2_3d":   m3["win_g2"],
                "hit_3d":      m3["hit"],
            })

        if i % 100 == 0:
            pct = round(i / total * 100, 1)
            print(f"[LOADER] {ativo}: {i}/{total} minutos processados ({pct}%)")

    print(f"[LOADER] ✅ {ativo}: {len(resultados)} registros gerados")
    return resultados


def run_loader() -> pd.DataFrame:
    """Processa todos os ativos e retorna DataFrame consolidado."""
    print(f"\n{'='*60}")
    print(f"[LOADER] Iniciando agregação — {len(ATIVOS)} ativos")
    print(f"{'='*60}\n")

    todos = []
    for ativo in ATIVOS:
        registros = agregar_ativo(ativo)
        todos.extend(registros)

    df_final = pd.DataFrame(todos)
    print(f"\n[LOADER] ✅ Total: {len(df_final)} registros prontos para upload")
    return df_final


if __name__ == "__main__":
    df = run_loader()
    print(df.head())
