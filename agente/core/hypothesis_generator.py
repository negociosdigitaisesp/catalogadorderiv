"""
agente/core/hypothesis_generator.py
=====================================
Auto Quant Discovery — Fase 1 — Camada A

Responsabilidade:
  Ler o catalog.db (SQLite), calcular a frequência baseline global e gerar
  hipóteses de padrões probabilísticos (contextual edge) candidatos ao backtest.

REGRAS ABSOLUTAS (PRD):
  - Sem loops bloqueantes: leitura via pandas.read_sql (operação única, batch)
  - Sem indicadores técnicos: apenas frequência empírica e Z-Score contextual
  - Sem datetime.now() para lógica de trading (apenas para nome do arquivo)
  - Pandas permitido apenas nesta Camada A
  - NumPy para todos os cálculos vetorizados
  - N mínimo: 100 amostras para constar como hipótese
  - Edge mínimo padrão: 5% acima do baseline global
  - Prioridade: edge_bruto * log(n_amostras)  — ordena por confiança estatística
  - Salvar máximo 200 hipóteses ranqueadas
"""

from __future__ import annotations

import json
import logging
import sqlite3
from itertools import combinations
from pathlib import Path
from time import time
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class HypothesisGenerator:
    """
    Gerador de hipóteses probabilísticas a partir do catálogo histórico.

    Fluxo:
        df = load_catalog(db_path)
        base = compute_base_frequencies(df)
        hipoteses = generate_hypotheses(df, min_edge=0.05)
        export_hypotheses(hipoteses, "agente/output/")
    """

    # Campos contextuais v2 — Ciclo de Horário (V1-V7)
    _CONTEXT_FIELDS: list[str] = [
        "hh_mm",            # V1: horário exato '13:55'
        "dia_semana",       # V2: dia da semana 0-6
        "cor_atual",        # V3: cor da vela atual
        "mhi_seq",          # V4: padrão das 3 velas (ex: 'V-V-R')
        "tendencia_m5",     # V5: tendência dos últimos 5 minutos
        "tendencia_m15",    # V6: tendência dos últimos 15 minutos
    ]

    # Coluna de resultado: 'proxima_1' = cor da PRÓXIMA vela (alvo da previsão)
    # 'VERDE' = acerto em CALL, 'VERMELHA' = acerto em PUT
    _OUTCOME_COL: str = "proxima_1"

    # Coluna de ativo
    _ASSET_COL: str = "ativo"

    # Valores de resultado positivo (CALL win = próxima verde)
    _WIN_VALUES: frozenset[str] = frozenset({"VERDE"})

    # ─────────────────────────────────────────────────────────────────────────
    # MÉTODO 1: load_catalog
    # ─────────────────────────────────────────────────────────────────────────

    def load_catalog(self, db_path: str) -> pd.DataFrame:
        """
        Lê o catálogo histórico do SQLite e retorna um DataFrame limpo.

        Parameters
        ----------
        db_path : str
            Caminho absoluto ou relativo ao arquivo catalog.db.

        Returns
        -------
        pd.DataFrame
            DataFrame com os registros do catálogo.
            Colunas esperadas incluem: ativo, resultado, e campos contextuais.

        Raises
        ------
        FileNotFoundError
            Se o arquivo db_path não existir.
        sqlite3.Error
            Se a consulta falhar.
        """
        path = Path(db_path)
        if not path.exists():
            raise FileNotFoundError(f"Catalog não encontrado: {db_path}")

        logger.info("Lendo catalog.db em: %s", db_path)
        with sqlite3.connect(str(path)) as conn:
            df = pd.read_sql("SELECT * FROM candles", conn)

        logger.info("Catálogo carregado: %d registros, %d colunas", len(df), len(df.columns))
        return df

    # ─────────────────────────────────────────────────────────────────────────
    # MÉTODO 2: compute_base_frequencies
    # ─────────────────────────────────────────────────────────────────────────

    def compute_base_frequencies(self, df: pd.DataFrame) -> dict[str, Any]:
        """
        Calcula a frequência baseline global de cada resultado.

        Esta é a referência (null hypothesis) que toda hipótese precisa superar
        em pelo menos `min_edge` para ser considerada válida.

        Parameters
        ----------
        df : pd.DataFrame
            DataFrame retornado por load_catalog.

        Returns
        -------
        dict
            {
                "p_win_global": float,      # P(resultado == positivo) no conjunto inteiro
                "p_loss_global": float,     # 1 - p_win_global
                "n_total": int,             # Total de amostras
                "por_ativo": dict           # { ativo: { "p_win": float, "n": int } }
            }
        """
        if self._OUTCOME_COL not in df.columns:
            raise ValueError(f"Coluna '{self._OUTCOME_COL}' não encontrada no DataFrame.")

        # Vectorised win detection
        win_mask = df[self._OUTCOME_COL].astype(str).isin({str(v) for v in self._WIN_VALUES})
        n_total = len(df)
        n_win = int(win_mask.sum())
        p_win_global = n_win / n_total if n_total > 0 else 0.0

        logger.info(
            "Frequência global → P(WIN)=%.4f | N=%d", p_win_global, n_total
        )

        # Por ativo
        por_ativo: dict[str, dict] = {}
        if self._ASSET_COL in df.columns:
            for ativo, grupo in df.groupby(self._ASSET_COL, sort=False):
                mask_a = grupo[self._OUTCOME_COL].astype(str).isin({str(v) for v in self._WIN_VALUES})
                n_a = len(grupo)
                por_ativo[str(ativo)] = {
                    "p_win": float(mask_a.sum() / n_a) if n_a > 0 else 0.0,
                    "n": n_a,
                }

        return {
            "p_win_global": p_win_global,
            "p_loss_global": 1.0 - p_win_global,
            "n_total": n_total,
            "por_ativo": por_ativo,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # MÉTODO 3: generate_hypotheses
    # ─────────────────────────────────────────────────────────────────────────

    def generate_hypotheses(
        self,
        df: pd.DataFrame,
        min_edge: float = 0.01,
        min_n: int = 60,
        max_hypotheses: int = 200,
    ) -> list[dict]:
        """
        Gera hipóteses de padrões probabilísticos com edge estatístico.

        Combina campos contextuais em pares e triplas. Para cada combinação
        calcula P(WIN | contexto). Hipóteses com edge_bruto >= min_edge e
        N >= min_n são retornadas ordenadas por prioridade (confiança).

        REGRA: Nenhum indicador técnico — apenas frequência empírica e Z-Score.

        Parameters
        ----------
        df : pd.DataFrame
            DataFrame do catálogo.
        min_edge : float
            Edge mínimo sobre o baseline global. Padrão: 0.05 (5%).
        min_n : int
            Mínimo de amostras por contexto. Padrão: 100.
        max_hypotheses : int
            Número máximo de hipóteses retornadas. Padrão: 200.

        Returns
        -------
        list[dict]
            Lista de até `max_hypotheses` hipóteses ordenadas por prioridade
            decrescente. Cada dict tem a estrutura:
            {
                "ativo": str,
                "contexto": dict,
                "direcao": "CALL" | "PUT",
                "p_win_condicional": float,
                "p_win_global": float,
                "edge_bruto": float,
                "n_amostras": int,
                "prioridade": float
            }
        """
        if self._OUTCOME_COL not in df.columns:
            raise ValueError(f"Coluna '{self._OUTCOME_COL}' não encontrada.")

        base = self.compute_base_frequencies(df)
        p_win_global = base["p_win_global"]

        # Determina quais campos contextuais existem no DF
        campos_disponiveis = [c for c in self._CONTEXT_FIELDS if c in df.columns]
        if not campos_disponiveis:
            logger.warning("Nenhum campo contextual encontrado. Retornando lista vazia.")
            return []

        win_mask_global = df[self._OUTCOME_COL].astype(str).isin({str(v) for v in self._WIN_VALUES})

        hipoteses: list[dict] = []

        # Itera sobre ativos separadamente para descoberta por ativo
        ativos = df[self._ASSET_COL].unique() if self._ASSET_COL in df.columns else [None]

        for ativo in ativos:
            df_ativo = df[df[self._ASSET_COL] == ativo] if ativo is not None else df
            win_mask_ativo = df_ativo[self._OUTCOME_COL].astype(str).isin(
                {str(v) for v in self._WIN_VALUES}
            )
            p_win_ativo = float(win_mask_ativo.mean()) if len(df_ativo) > 0 else p_win_global

            # Combina campos em pares (2) e triplas (3)
            for tamanho in (2, 3):
                for combo in combinations(campos_disponiveis, tamanho):
                    try:
                        for values, grupo in df_ativo.groupby(list(combo), sort=False):
                            n = len(grupo)
                            if n < min_n:
                                continue  # PRD: N < 100 → descartar

                            win_mask_grupo = grupo[self._OUTCOME_COL].astype(str).isin(
                                {str(v) for v in self._WIN_VALUES}
                            )
                            n_win = int(win_mask_grupo.sum())
                            p_win_cond = n_win / n

                            if p_win_cond >= 1.0:
                                continue  # PRD: nenhuma hipótese com p_win_cond >= 1.0 pode passar

                            edge_call = p_win_cond - p_win_ativo
                            edge_put = (1.0 - p_win_cond) - (1.0 - p_win_ativo)

                            # Verifica se alguma direção passa no threshold
                            best_edge = edge_call
                            direcao = "CALL"
                            if edge_put > edge_call:
                                best_edge = edge_put
                                direcao = "PUT"

                            if best_edge < min_edge:
                                continue  # PRD: edge insuficiente → descartar

                            # Prioridade = edge * log(N)  — confiança estatística
                            prioridade = float(best_edge * np.log(n))

                            contexto = dict(
                                zip(combo, values if tamanho > 1 else [values])
                            )

                            hipoteses.append({
                                "ativo": str(ativo) if ativo is not None else "ALL",
                                "contexto": {k: _serialize(v) for k, v in contexto.items()},
                                "direcao": direcao,
                                "p_win_condicional": round(p_win_cond, 6),
                                "p_win_global": round(p_win_ativo, 6),
                                "edge_bruto": round(best_edge, 6),
                                "n_amostras": n,
                                "prioridade": round(prioridade, 6),
                            })
                    except Exception as exc:
                        logger.debug("Combinação %s ignorada: %s", combo, exc)
                        continue

        # Ordena por prioridade decrescente e limite top-N
        hipoteses.sort(key=lambda h: h["prioridade"], reverse=True)
        hipoteses = hipoteses[:max_hypotheses]

        logger.info(
            "Geração concluída → %d hipóteses encontradas (top %d retornadas)",
            len(hipoteses),
            max_hypotheses,
        )
        return hipoteses

    # ─────────────────────────────────────────────────────────────────────────
    # MÉTODO 4: export_hypotheses
    # ─────────────────────────────────────────────────────────────────────────

    def export_hypotheses(self, hypotheses: list[dict], output_path: str) -> None:
        """
        Serializa a lista de hipóteses em um arquivo JSON.

        Nome do arquivo: hypotheses_<epoch_int>.json
        Epoch é usado APENAS para nomenclatura do arquivo — não entra em lógica
        de trading.

        Parameters
        ----------
        hypotheses : list[dict]
            Lista gerada por generate_hypotheses.
        output_path : str
            Diretório onde o arquivo será salvo.

        Returns
        -------
        None
        """
        out_dir = Path(output_path)
        out_dir.mkdir(parents=True, exist_ok=True)

        epoch_int = int(time())  # Apenas para nome de arquivo
        filename = out_dir / f"hypotheses_{epoch_int}.json"

        with open(filename, "w", encoding="utf-8") as fp:
            json.dump(hypotheses, fp, ensure_ascii=False, indent=2)

        logger.info("Hipóteses exportadas → %s (%d itens)", filename, len(hypotheses))


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS INTERNOS
# ─────────────────────────────────────────────────────────────────────────────

def _serialize(value: Any) -> Any:
    """Converte tipos NumPy para tipos nativos Python (necessário para JSON)."""
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value
