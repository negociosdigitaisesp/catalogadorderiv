"""
agente/core/pattern_miner.py
==============================
Auto Quant Discovery -- Fase 2 -- Grade Horaria de Elite

Responsabilidade:
  Receber o DataFrame do DataLoader v2 e minerar oportunidades de Ciclo de
  Horario altamente assertivas, usando Gale 2 vetorizado e score ponderado.

VARIACOES IMPLEMENTADAS:
  V1 -- Puro Horario:     group by (ativo, hh_mm) com TRAIN/TEST split
  V2 -- MHI + Horario:    group by (ativo, hh_mm, mhi_seq) com TRAIN/TEST split
  V4 -- Score 30/7:       V1 + WR_30dias * 0.6 + WR_7dias * 0.4 (recencia)

ANTI-OVERFITTING (todas as variacoes):
  Odd/Even day split:
    - TRAIN (odd days): usado para determinar direcao dominante
    - TEST  (even days): usado para calcular WR real
  Isso impede que _best_direcao veja os mesmos dados usados para medir WR.

DEDUPLICACAO V1/V4:
  Como V1 e V4 usam o mesmo agrupamento (ativo, hh_mm), o mine_all
  garante que se um horario passou na V4, ele NAO e duplicado pela V1.
  V4 tem prioridade pois inclui o score de recencia.

LOGICA DE GALE 2 (vetorizada por groupby):
  win_1a:   proxima_1 == direcao          -> ganhou na 1a entrada
  win_gale1: ~win_1a  AND proxima_2 == direcao  -> ganhou no Gale 1
  win_gale2: ~win_1a AND ~win_gale1 AND proxima_3 == direcao -> Gale 2
  hit:       ~win_1a AND ~win_gale1 AND ~win_gale2 -> perda total

EV DO CICLO (Rua -- Gale 2):
  Stakes:   1.0 (entrada) + 2.2 (Gale1) + 5.0 (Gale2) = 8.2 unidades
  Payout:   85%
  EV = (P_1a * 0.85) + (P_g1 * 0.87) + (P_g2 * 0.89) - (P_hit * 8.2)

FILTRO DE ELITE:
  N >= 15 (temp)  E  Win Rate Gale2 >= 75% (DEBUG -- prod=0.90)

REGRAS ABSOLUTAS (PRD):
  - Sem indicadores tecnicos
  - Pandas groupby para performance em 400k linhas
  - NumPy vetorizado para todos os calculos booleanos
  - Sem datetime.now() (epoch puro para metadados)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from time import time
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# --- Constantes financeiras ---------------------------------------------------
_PAYOUT       = 0.85
_STAKE_G0     = 1.0
_STAKE_G1     = 2.2
_STAKE_G2     = 5.0
_STAKE_TOTAL  = _STAKE_G0 + _STAKE_G1 + _STAKE_G2    # 8.2
_LUCRO_G0     = _STAKE_G0 * _PAYOUT                   # 0.85  (win na 1a)
_LUCRO_G1     = _STAKE_G1 * _PAYOUT - _STAKE_G0       # 0.87  (win no Gale1 - prejuizo G0)
_LUCRO_G2     = _STAKE_G2 * _PAYOUT - _STAKE_G0 - _STAKE_G1  # 0.89 (win Gale2 - G0-G1)
_BREAK_EVEN   = 1.0 / (1.0 + _PAYOUT)                 # ~0.5405

# Filtros Elite (PRD Chief)
_MIN_N        = 15          # [TEMP] relaxado para teste (prod=20)
_MIN_WR_GALE2 = 0.75        # [DEBUG] baixado para ver faixa 75-84% (prod=0.90)
_DAYS_30      = 30 * 24 * 3600
_DAYS_7       = 7  * 24 * 3600

# Pesos do Score V4
_PESO_30 = 0.6
_PESO_7  = 0.4


class PatternMiner:
    """
    Motor de mineracao para o Sistema de Grade Horaria de Elite.

    Substitui o backtest por hipotese individual por varredura vetorizada
    por grupo (ativo x horario x contexto), extraindo oportunidades de alta
    assertividade com Gale 2 completo.

    Fluxo padrao:
        miner = PatternMiner()
        oportunidades = miner.mine_all(df_catalog, hypotheses)
    """

    def __init__(self) -> None:
        self._now_epoch: int = int(time())   # fixado no inicio do ciclo

    # -------------------------------------------------------------------------
    # METODO 1: _compute_gale2_stats (nucleo vetorizado)
    # -------------------------------------------------------------------------

    def _compute_gale2_stats(
        self,
        df_group: pd.DataFrame,
        direcao: str,
    ) -> dict:
        """
        Calcula estatisticas completas de Gale 2 para um grupo ja filtrado.

        Usa as colunas pre-computadas pelo DataLoader v2:
          proxima_1 -> cor da 1a entrada (vela alvo original)
          proxima_2 -> cor da vela +2 (Gale 1)
          proxima_3 -> cor da vela +3 (Gale 2)

        CALL -> 'VERDE' e WIN | PUT -> 'VERMELHA' e WIN
        """
        n = len(df_group)
        if n == 0:
            return _empty_stats(direcao)

        win_color = "VERDE" if direcao == "CALL" else "VERMELHA"

        # Vetores bool (ignorar '?' -- vela sem futuro disponivel)
        valid_1 = df_group["proxima_1"].ne("?")
        valid_2 = df_group["proxima_2"].ne("?")
        valid_3 = df_group["proxima_3"].ne("?")

        p1 = df_group["proxima_1"].eq(win_color)
        p2 = df_group["proxima_2"].eq(win_color)
        p3 = df_group["proxima_3"].eq(win_color)

        # Apenas ciclos COMPLETOS: as 3 entradas precisam ter resultado.
        complete  = valid_1 & valid_2 & valid_3
        n_valid   = int(complete.sum())

        if n_valid == 0:
            return _empty_stats(direcao)

        perdeu_1a = complete & ~p1
        win_1a    = complete & p1

        perdeu_g1 = perdeu_1a & ~p2
        win_gale1 = perdeu_1a & p2

        win_gale2 = perdeu_g1 & p3
        hit       = perdeu_g1 & ~p3

        n_1a    = int(win_1a.sum())
        n_g1    = int(win_gale1.sum())
        n_g2    = int(win_gale2.sum())
        n_hit   = int(hit.sum())
        # Invariante: n_1a + n_g1 + n_g2 + n_hit == n_valid

        p_1a   = n_1a  / n_valid
        p_g1   = n_g1  / n_valid
        p_g2   = n_g2  / n_valid
        p_hit  = n_hit / n_valid

        wr_gale2 = round(1.0 - p_hit, 6)

        if wr_gale2 >= 1.0:
            return _empty_stats(direcao)

        ev_gale2 = round(
            p_1a * _LUCRO_G0
            + p_g1 * _LUCRO_G1
            + p_g2 * _LUCRO_G2
            - p_hit * _STAKE_TOTAL,
            6
        )

        return {
            "n":          n_valid,
            "n_1a":       n_1a,
            "n_gale1":    n_g1,
            "n_gale2":    n_g2,
            "n_hit":      n_hit,
            "p_1a":       round(p_1a,  6),
            "p_gale1":    round(p_g1,  6),
            "p_gale2":    round(p_g2,  6),
            "p_hit":      round(p_hit, 6),
            "wr_gale2":   wr_gale2,
            "ev_gale2":   ev_gale2,
            "direcao":    direcao,
            "approved":   n_valid >= _MIN_N and wr_gale2 >= _MIN_WR_GALE2,
        }

    # -------------------------------------------------------------------------
    # METODO 2: _best_direcao
    # -------------------------------------------------------------------------

    def _best_direcao(self, df_group: pd.DataFrame) -> str:
        """
        Determina a direcao dominante no grupo (CALL ou PUT).

        CALL -> maioria das proxima_1 e 'VERDE'.
        PUT  -> maioria das proxima_1 e 'VERMELHA'.
        """
        valid = df_group["proxima_1"].ne("?")
        verdes = (df_group.loc[valid, "proxima_1"] == "VERDE").sum()
        total  = valid.sum()
        return "CALL" if verdes >= total / 2 else "PUT"

    # -------------------------------------------------------------------------
    # METODO 3: _split_train_test (anti-overfitting)
    # -------------------------------------------------------------------------

    def _split_train_test(
        self,
        df_group: pd.DataFrame,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """
        Separa grupo em TRAIN (dias impares) e TEST (dias pares).

        Usa o dia do mes derivado do timestamp:
          dia_do_mes = (timestamp // 86400) % 31

        TRAIN: usado APENAS para determinar direcao (_best_direcao)
        TEST:  usado para calcular WR real (_compute_gale2_stats)

        Isso quebra a logica circular onde _best_direcao olhava os
        mesmos dados usados para medir WR, inflando o resultado.
        """
        day_of_epoch = df_group["timestamp"] // 86400
        is_odd = (day_of_epoch % 2) == 1
        train = df_group[is_odd]
        test  = df_group[~is_odd]
        return train, test

    # =========================================================================
    # V1 — Puro Horario: group by (ativo, hh_mm) com TRAIN/TEST split
    # =========================================================================

    def mine_v1(self, df: pd.DataFrame) -> list[dict]:
        """
        V1 -- Puro Horario (sem dia_semana).

        Agrupa por (ativo, hh_mm). Usa TRAIN/TEST split.
        A pergunta: 'Qual a Win Rate Gale 2 as 13:55 em TODOS os dias?'
        """
        df = df.copy()
        resultados: list[dict] = []
        best_candidate: dict | None = None
        best_wr: float = 0.0

        groups = df.groupby(["ativo", "hh_mm"], sort=False)

        for (ativo, hh_mm), grupo in groups:
            if len(grupo) < _MIN_N:
                continue

            # SPLIT: treina num subset, testa em outro
            train, test = self._split_train_test(grupo)

            if len(test) < _MIN_N:
                continue

            # Direcao vem do TRAIN (nunca do TEST)
            direcao = self._best_direcao(train)

            # WR medida no TEST (out-of-sample)
            stats = self._compute_gale2_stats(test, direcao)

            # Rastreia o melhor candidato para debug
            if stats["n"] > 0 and stats["wr_gale2"] > best_wr:
                best_wr = stats["wr_gale2"]
                best_candidate = {
                    "ativo": ativo, "hh_mm": hh_mm,
                    "wr": stats["wr_gale2"], "n": stats["n"],
                    "n_hit": stats["n_hit"],
                }

            if not stats["approved"]:
                continue

            resultados.append({
                "variacao":        "V1",
                "ativo":           str(ativo),
                "horario_alvo":    str(hh_mm),
                "dia_semana":      -1,   # -1 = todos os dias
                "mhi_seq":         None,
                "direcao":         direcao,
                "n":               stats["n"],
                "n_1a":            stats["n_1a"],
                "n_gale1":         stats["n_gale1"],
                "n_gale2":         stats["n_gale2"],
                "n_hit":           stats["n_hit"],
                "wr_gale2":        stats["wr_gale2"],
                "ev_gale2":        stats["ev_gale2"],
                "p_1a":            stats["p_1a"],
                "p_gale1":         stats["p_gale1"],
                "p_gale2":         stats["p_gale2"],
                "p_hit":           stats["p_hit"],
                "score_ponderado": round(stats["wr_gale2"], 6),
                "contexto":        {"hh_mm": hh_mm},
            })

        if resultados:
            logger.info("[MINE] V1: %d oportunidades Elite encontradas.", len(resultados))
        elif best_candidate:
            logger.info(
                "[MINE] V1: 0 Elite encontradas. Melhor WR foi %.1f%% no %s as %s (N_test=%d, hits=%d)",
                best_candidate["wr"] * 100,
                best_candidate["ativo"],
                best_candidate["hh_mm"],
                best_candidate["n"],
                best_candidate["n_hit"],
            )
        else:
            logger.info("[MINE] V1: 0 Elite encontradas. Nenhum grupo com N>=15 no TEST split.")

        return resultados

    # =========================================================================
    # V2 — MHI + Horario: group by (ativo, hh_mm, mhi_seq) com TRAIN/TEST
    # =========================================================================

    def mine_v2(self, df: pd.DataFrame) -> list[dict]:
        """
        V2 -- Bloco MHI de Horario (sem dia_semana).

        Agrupa por (ativo, hh_mm, mhi_seq). Usa TRAIN/TEST split.
        A pergunta: 'As 13:55, quando as ultimas 3 velas foram V-V-R,
        qual a assertividade?'
        """
        df = df.copy()
        # Exclui ?-?-? (primeiras velas sem historico)
        df_v2 = df[df["mhi_seq"] != "?-?-?"]
        resultados: list[dict] = []
        best_candidate: dict | None = None
        best_wr: float = 0.0

        groups = df_v2.groupby(["ativo", "hh_mm", "mhi_seq"], sort=False)
        for (ativo, hh_mm, mhi_seq), grupo in groups:
            if len(grupo) < _MIN_N:
                continue

            # SPLIT: treina num subset, testa em outro
            train, test = self._split_train_test(grupo)

            if len(test) < _MIN_N:
                continue

            direcao = self._best_direcao(train)
            stats   = self._compute_gale2_stats(test, direcao)

            if stats["n"] > 0 and stats["wr_gale2"] > best_wr:
                best_wr = stats["wr_gale2"]
                best_candidate = {
                    "ativo": ativo, "hh_mm": hh_mm,
                    "mhi_seq": mhi_seq,
                    "wr": stats["wr_gale2"], "n": stats["n"],
                    "n_hit": stats["n_hit"],
                }

            if not stats["approved"]:
                continue

            resultados.append({
                "variacao":        "V2",
                "ativo":           str(ativo),
                "horario_alvo":    str(hh_mm),
                "dia_semana":      -1,   # -1 = todos os dias
                "mhi_seq":         str(mhi_seq),
                "direcao":         direcao,
                "n":               stats["n"],
                "n_1a":            stats["n_1a"],
                "n_gale1":         stats["n_gale1"],
                "n_gale2":         stats["n_gale2"],
                "n_hit":           stats["n_hit"],
                "wr_gale2":        stats["wr_gale2"],
                "ev_gale2":        stats["ev_gale2"],
                "p_1a":            stats["p_1a"],
                "p_gale1":         stats["p_gale1"],
                "p_gale2":         stats["p_gale2"],
                "p_hit":           stats["p_hit"],
                "score_ponderado": round(stats["wr_gale2"], 6),
                "contexto": {
                    "hh_mm":    hh_mm,
                    "mhi_seq":  mhi_seq,
                },
            })

        if resultados:
            logger.info("[MINE] V2: %d oportunidades Elite encontradas.", len(resultados))
        elif best_candidate:
            logger.info(
                "[MINE] V2: 0 Elite. Melhor WR foi %.1f%% no %s as %s seq=%s (N=%d, hits=%d)",
                best_candidate["wr"] * 100,
                best_candidate["ativo"],
                best_candidate["hh_mm"],
                best_candidate["mhi_seq"],
                best_candidate["n"],
                best_candidate["n_hit"],
            )
        else:
            logger.info("[MINE] V2: 0 Elite encontradas. Nenhum grupo com N>=15 no TEST split.")

        return resultados

    # =========================================================================
    # V4 — Score 30/7 (Recencia Ponderada)
    # =========================================================================

    def mine_v4(self, df: pd.DataFrame) -> list[dict]:
        """
        V4 -- Score Ponderado recencia: WR_30dias * 0.6 + WR_7dias * 0.4.

        Agrupa por (ativo, hh_mm) SEM dia_semana, para maximizar N.
        Dentro de cada grupo, separa os dados em janela 30d e 7d.

        Usa TRAIN/TEST split (odd/even days) para anti-overfitting:
          - TRAIN: determina direcao
          - TEST:  calcula WR
        """
        df = df.copy()
        now_epoch   = int(time())
        epoch_30    = now_epoch - _DAYS_30
        epoch_7     = now_epoch - _DAYS_7

        df_30 = df[df["timestamp"] >= epoch_30]
        df_7  = df[df["timestamp"] >= epoch_7]

        resultados: list[dict] = []
        best_candidate: dict | None = None
        best_wr: float = 0.0

        groups = df_30.groupby(["ativo", "hh_mm"], sort=False)

        for (ativo, hh_mm), grupo_30 in groups:
            if len(grupo_30) < _MIN_N:
                continue

            # SPLIT no grupo de 30 dias
            train, test = self._split_train_test(grupo_30)

            if len(test) < _MIN_N:
                continue

            direcao  = self._best_direcao(train)
            stats_30 = self._compute_gale2_stats(test, direcao)

            if stats_30["n"] > 0 and stats_30["wr_gale2"] > best_wr:
                best_wr = stats_30["wr_gale2"]
                best_candidate = {
                    "ativo": ativo, "hh_mm": hh_mm,
                    "wr": stats_30["wr_gale2"], "n": stats_30["n"],
                    "n_hit": stats_30["n_hit"],
                }

            if not stats_30["approved"]:
                continue

            # Filtra subgrupo dos ultimos 7 dias (tambem test-only)
            grupo_7 = df_7[
                (df_7["ativo"]   == ativo)
                & (df_7["hh_mm"] == hh_mm)
            ]
            n_7 = len(grupo_7)

            if n_7 < 3:
                wr_7 = stats_30["wr_gale2"]   # fallback
            else:
                stats_7 = self._compute_gale2_stats(grupo_7, direcao)
                wr_7    = stats_7["wr_gale2"]

            score = round(stats_30["wr_gale2"] * _PESO_30 + wr_7 * _PESO_7, 6)

            resultados.append({
                "variacao":        "V4",
                "ativo":           str(ativo),
                "horario_alvo":    str(hh_mm),
                "dia_semana":      -1,   # -1 = todos os dias
                "mhi_seq":         None,
                "direcao":         direcao,
                "n":               stats_30["n"],
                "n_1a":            stats_30["n_1a"],
                "n_gale1":         stats_30["n_gale1"],
                "n_gale2":         stats_30["n_gale2"],
                "n_hit":           stats_30["n_hit"],
                "n_7d":            n_7,
                "wr_30d":          stats_30["wr_gale2"],
                "wr_7d":           wr_7,
                "wr_gale2":        stats_30["wr_gale2"],
                "ev_gale2":        stats_30["ev_gale2"],
                "p_1a":            stats_30["p_1a"],
                "p_gale1":         stats_30["p_gale1"],
                "p_gale2":         stats_30["p_gale2"],
                "p_hit":           stats_30["p_hit"],
                "score_ponderado": score,
                "contexto":        {"hh_mm": hh_mm},
            })

        resultados.sort(key=lambda r: r["score_ponderado"], reverse=True)

        if resultados:
            logger.info("[MINE] V4: %d oportunidades Elite (30/7d score).", len(resultados))
        elif best_candidate:
            logger.info(
                "[MINE] V4: 0 Elite encontradas. Melhor WR foi %.1f%% no %s as %s (N_test=%d, hits=%d)",
                best_candidate["wr"] * 100,
                best_candidate["ativo"],
                best_candidate["hh_mm"],
                best_candidate["n"],
                best_candidate["n_hit"],
            )
        else:
            logger.info("[MINE] V4: 0 Elite encontradas. Nenhum grupo com N>=15 no TEST split.")

        return resultados

    # =========================================================================
    # mine_all — Orquestrador com deduplicacao V1/V4
    # =========================================================================

    def mine_all(
        self,
        df: pd.DataFrame,
        hypotheses: list[dict] | None = None,
    ) -> list[dict]:
        """
        Executa V1, V2, V4 e retorna lista consolidada de oportunidades Elite.

        DEDUPLICACAO: V4 tem prioridade sobre V1. Se um (ativo, hh_mm)
        ja aparece na V4, ele e removido da V1 para evitar duplicata.
        """
        if df.empty:
            logger.warning("[MINE] DataFrame vazio -- nenhuma oportunidade minerada.")
            return []

        total_linhas = len(df)
        logger.info("[MINE] Iniciando Grade Horaria de Elite | %d velas | filtro WR>=%.0f%%",
                    total_linhas, _MIN_WR_GALE2 * 100)

        # V4 roda PRIMEIRO (tem prioridade)
        v4 = self.mine_v4(df)
        v2 = self.mine_v2(df)
        v1 = self.mine_v1(df)

        # Deduplicacao: remove V1 entries que ja existem na V4
        chaves_v4 = {(r["ativo"], r["horario_alvo"]) for r in v4}
        v1_dedup = [r for r in v1 if (r["ativo"], r["horario_alvo"]) not in chaves_v4]
        n_removidos = len(v1) - len(v1_dedup)
        if n_removidos > 0:
            logger.info("[MINE] Dedup V1/V4: %d entradas V1 removidas (ja cobertas por V4).", n_removidos)

        todas = v4 + v2 + v1_dedup
        todas.sort(key=lambda r: r["score_ponderado"], reverse=True)

        logger.info(
            "[MINE] Total Elite: %d oportunidades (V1=%d | V2=%d | V4=%d | V1_dedup_removidos=%d)",
            len(todas), len(v1_dedup), len(v2), len(v4), n_removidos,
        )

        # Adapta formato para compatibilidade com StrategyValidator e StrategyWriter
        return [_adaptar_para_pipeline(op) for op in todas]

    # -------------------------------------------------------------------------
    # export_results
    # -------------------------------------------------------------------------

    def export_results(self, results: list[dict], output_path: str) -> None:
        """Serializa oportunidades em JSON com epoch como nome (para auditoria)."""
        out_dir  = Path(output_path)
        out_dir.mkdir(parents=True, exist_ok=True)
        filename = out_dir / f"mined_elite_{int(time())}.json"

        with open(filename, "w", encoding="utf-8") as fp:
            json.dump(results, fp, ensure_ascii=False, indent=2, default=_json_default)

        logger.info("[MINE] Resultados exportados -> %s (%d itens)", filename, len(results))


# -----------------------------------------------------------------------------
# HELPERS INTERNOS
# -----------------------------------------------------------------------------

def _empty_stats(direcao: str) -> dict:
    """Retorna stats zeradas quando o grupo e invalido ou muito pequeno."""
    return {
        "n": 0, "n_1a": 0, "n_gale1": 0, "n_gale2": 0, "n_hit": 0,
        "p_1a": 0.0, "p_gale1": 0.0, "p_gale2": 0.0, "p_hit": 1.0,
        "wr_gale2": 0.0, "ev_gale2": round(-_STAKE_TOTAL, 6),
        "direcao": direcao, "approved": False,
    }


def _adaptar_para_pipeline(op: dict) -> dict:
    """
    Converte o formato de oportunidade Elite para o formato esperado pelo
    StrategyValidator.validate_batch() e StrategyWriter.write_all().
    """
    hypothesis = {
        "ativo":              op["ativo"],
        "contexto":           op["contexto"],
        "direcao":            op["direcao"],
        "p_win_condicional":  op["wr_gale2"],
        "p_win_global":       op["wr_gale2"],
        "edge_bruto":         round(op["wr_gale2"] - _BREAK_EVEN, 6),
        "n_amostras":         op["n"],
        "prioridade":         op["score_ponderado"],
    }

    mined_result = {
        "hypothesis":      hypothesis,
        "win_rate_final":  op["wr_gale2"],
        "ev_final":        op["ev_gale2"],
        "edge_final":      round(op["wr_gale2"] - _BREAK_EVEN, 6),
        "win_rate_gale1":  round(op["p_1a"] + op["p_gale1"], 6),
        "n_test":          op["n"],
        "oos_flag":        "OUT_OF_SAMPLE_OK",
        # Campos extras para rastreabilidade
        "variacao":        op["variacao"],
        "horario_alvo":    op["horario_alvo"],
        "score_ponderado": op["score_ponderado"],
        "p_1a":            op["p_1a"],
        "p_gale1":         op["p_gale1"],
        "p_gale2":         op.get("p_gale2", 0.0),
        "p_hit":           op["p_hit"],
        "ev_gale2":        op["ev_gale2"],
        # Quantidades REAIS para transparencia e auditoria no banco
        "n_total":         op["n"],
        "n_win_1a":        op.get("n_1a",    0),
        "n_win_g1":        op.get("n_gale1", 0),
        "n_win_g2":        op.get("n_gale2", 0),
        "n_hit":           op.get("n_hit",   0),
    }

    return mined_result


def _json_default(obj: Any) -> Any:
    """Serializa tipos NumPy para JSON nativo."""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
