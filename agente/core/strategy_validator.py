"""
agente/core/strategy_validator.py
=====================================
Auto Quant Discovery — Fase 3 — Validador: Funil de EV & Qualidade de Entrada

Responsabilidade:
  Receber oportunidades mineradas pelo PatternMiner e classificá-las em
  APROVADO / CONDICIONAL / REPROVADO usando o Funil de Valor Esperado.

LÓGICA DE VALIDAÇÃO (Funil de 4 Cortes + Regra de Ouro):

  CORTE 1 — Amostragem:   n_total < 15             → REPROVADO
  CORTE 2 — Assertividade: wr_gale2 < 88%          → REPROVADO
  CORTE 3 — Lucratividade: ev_gale2 <= 0.0         → REPROVADO
  CORTE 4 — V7 Hit Seq:    max_consec_hit >= 3     → REPROVADO

  REGRA DE OURO (APROVADO — Stake 1.0):
    ev_gale2 > 0.10  AND  wr_gale2 >= 90%  AND  p_1a >= 55%

  CONTENÇÃO (CONDICIONAL — Stake 0.5):
    Passou nos 4 cortes mas falhou em algum requisito da Regra de Ouro.

  TRAVA ANTI-DUPLICATA:
    Se ativo + hh_mm + direcao já foi APROVADO em outra variação,
    força para CONDICIONAL (não alavancar risco duplo no mesmo minuto).

SIZING:
  APROVADO    → stake_multiplier = 1.0
  CONDICIONAL → stake_multiplier = 0.5

REGRAS ABSOLUTAS (PRD):
  - Sem Sharpe, Binomial, Monte Carlo
  - Sem datetime.now()
"""

from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)

# ─── Thresholds do Funil de EV ────────────────────────────────────────────────

# Cortes obrigatórios (REPROVADO se falhar)
_N_MIN       = 15      # Corte 1: Amostragem mínima
_WR_MIN      = 0.88    # Corte 2: Assertividade G2 mínima (88%)
_EV_MIN      = 0.0     # Corte 3: EV estritamente positivo

# V7: Sequência máxima de Hit consecutivo
_MAX_CONSEC  = 3

# Regra de Ouro (APROVADO = Stake 1.0)
_EV_ELITE    = 0.10    # EV > 0.10 (lucratividade sólida)
_WR_ELITE    = 0.90    # WR G2 >= 90% (assertividade Elite)
_P1A_ELITE   = 0.55    # P(1ª) >= 55% (não refém do Gale)

# Sizing
_STAKE_APROVADO    = 1.0
_STAKE_CONDICIONAL = 0.5


class StrategyValidator:
    """
    Validador da Grade Horária de Elite — Funil de EV & Qualidade de Entrada.

    Foco em 3 decisões práticas:
      1. O horário é lucrativo? (EV > 0)
      2. O horário é assertivo? (WR G2 >= 88%)
      3. O horário acerta de primeira? (P_1A >= 55%)

    Uso típico:
        validator = StrategyValidator()
        batch = validator.validate_batch(mined_results)
    """

    # ─────────────────────────────────────────────────────────────────────────
    # MÉTODO CENTRAL: validate
    # ─────────────────────────────────────────────────────────────────────────

    def validate(self, mined_result: dict) -> dict:
        """
        Valida uma única oportunidade minerada pelo PatternMiner.

        Espera o formato do PatternMiner._adaptar_para_pipeline():
          mined_result['win_rate_final']  → wr_gale2
          mined_result['n_total']         → N amostras
          mined_result['p_1a']            → taxa 1ª entrada
          mined_result['p_gale1']         → taxa acumulada Gale 1
          mined_result['p_gale2']         → taxa acumulada Gale 2
          mined_result['p_hit']           → taxa Hit (perda total)
          mined_result['ev_final']        → EV Gale 2
          mined_result['hypothesis']      → dict com ativo, contexto, direcao

        Retorna:
          {
            status, stake_multiplier, motivo,
            win_1a_rate, win_gale1_rate, win_gale2_rate, hit_rate,
            ev_gale2, mined_result
          }
        """
        # Extrai métricas
        wr_gale2 = float(mined_result.get("win_rate_final", 0.0))
        n        = int(mined_result.get("n_total", mined_result.get("n_test", 0)))
        p_1a     = float(mined_result.get("p_1a",    0.0))
        p_gale1  = float(mined_result.get("p_gale1", 0.0))
        p_gale2  = float(mined_result.get("p_gale2", 0.0))
        p_hit    = float(mined_result.get("p_hit",   1.0))
        ev_gale2 = float(mined_result.get("ev_final", 0.0))

        kw = dict(p_1a=p_1a, p_gale1=p_gale1, p_gale2=p_gale2,
                  p_hit=p_hit, ev_gale2=ev_gale2, mined=mined_result)

        # ── CORTE 1: Amostragem insuficiente ─────────────────────────────
        if n < _N_MIN:
            return self._resultado(
                status="REPROVADO",
                motivo=f"Dados Insuficientes (N={n}, min={_N_MIN})",
                stake=0.0, **kw,
            )

        # ── CORTE 2: Assertividade G2 abaixo do limiar ──────────────────
        if wr_gale2 < _WR_MIN:
            return self._resultado(
                status="REPROVADO",
                motivo=f"Assertividade abaixo de {_WR_MIN:.0%} (WR={wr_gale2:.1%})",
                stake=0.0, **kw,
            )

        # ── CORTE 3: EV negativo ou zero (custo > lucro) ────────────────
        if ev_gale2 <= _EV_MIN:
            return self._resultado(
                status="REPROVADO",
                motivo=f"EV não-positivo (EV={ev_gale2:+.4f})",
                stake=0.0, **kw,
            )

        # ── CORTE 4 (V7): Hit sequencial perigoso ───────────────────────
        max_consec = _max_consecutive_loss(mined_result)
        if max_consec >= _MAX_CONSEC:
            return self._resultado(
                status="REPROVADO",
                motivo=f"Hit sequencial perigoso (max_consec={max_consec} >= {_MAX_CONSEC})",
                stake=0.0, **kw,
            )

        # ── REGRA DE OURO: APROVADO (Stake 1.0) ─────────────────────────
        is_elite = (
            ev_gale2  > _EV_ELITE
            and wr_gale2 >= _WR_ELITE
            and p_1a     >= _P1A_ELITE
        )
        if is_elite:
            return self._resultado(
                status="APROVADO",
                motivo=(
                    f"Elite (EV={ev_gale2:+.4f}, WR={wr_gale2:.1%}, "
                    f"P1A={p_1a:.1%})"
                ),
                stake=_STAKE_APROVADO, **kw,
            )

        # ── CONTENÇÃO: CONDICIONAL (Stake 0.5) ──────────────────────────
        # Passou nos 4 cortes mas falhou na Regra de Ouro
        falhas = []
        if ev_gale2 <= _EV_ELITE:
            falhas.append(f"EV={ev_gale2:+.4f}<{_EV_ELITE}")
        if wr_gale2 < _WR_ELITE:
            falhas.append(f"WR={wr_gale2:.1%}<{_WR_ELITE:.0%}")
        if p_1a < _P1A_ELITE:
            falhas.append(f"P1A={p_1a:.1%}<{_P1A_ELITE:.0%}")

        return self._resultado(
            status="CONDICIONAL",
            motivo=f"Lucrativo mas não Elite ({', '.join(falhas)})",
            stake=_STAKE_CONDICIONAL, **kw,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # MÉTODO AUXILIAR: _resultado
    # ─────────────────────────────────────────────────────────────────────────

    def _resultado(
        self,
        status: str,
        motivo: str,
        stake: float,
        p_1a: float,
        p_gale1: float,
        p_gale2: float,
        p_hit: float,
        ev_gale2: float,
        mined: dict,
    ) -> dict:
        """Monta o dicionário de resultado padronizado."""
        hyp = mined.get("hypothesis", {})
        logger.info(
            "[VALIDATOR] %s / %s | status=%s",
            hyp.get("ativo", "?"),
            hyp.get("contexto", {}),
            status,
        )
        return {
            "status":           status,
            "motivo":           motivo,
            "stake_multiplier": stake,
            # Taxas de Gale detalhadas
            "win_1a_rate":      round(p_1a,    6),
            "win_gale1_rate":   round(p_gale1, 6),
            "win_gale2_rate":   round(p_gale2, 6),
            "hit_rate":         round(p_hit,   6),
            "ev_gale2":         round(ev_gale2, 6),
            # Compatibilidade com StrategyWriter
            "kelly_quarter":    stake / 4.0,
            "status_aprovacao": status,
            "mined_result":     mined,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # MÉTODO PRINCIPAL: validate_batch
    # ─────────────────────────────────────────────────────────────────────────

    def validate_batch(self, mined_results: list[dict]) -> dict:
        """
        Valida um batch completo e retorna agrupado por status.

        Inclui TRAVA ANTI-DUPLICATA: se ativo + hh_mm + direcao
        já foi APROVADO em outra variação, força para CONDICIONAL.

        Retorna
        -------
        dict  { "aprovados": [...], "condicionais": [...], "reprovados": [...] }
        """
        aprovados:    list[dict] = []
        condicionais: list[dict] = []
        reprovados:   list[dict] = []

        # Rastreia chaves já aprovadas para trava anti-duplicata
        chaves_aprovadas: set[str] = set()

        for mined in mined_results:
            resultado = self.validate(mined)
            status    = resultado["status"]

            # ── Trava anti-duplicata ─────────────────────────────────────
            if status in ("APROVADO", "CONDICIONAL"):
                hyp    = mined.get("hypothesis", {})
                ctx    = hyp.get("contexto", {})
                chave  = f"{hyp.get('ativo','?')}|{ctx.get('hh_mm','?')}|{hyp.get('direcao','?')}"

                if status == "APROVADO":
                    if chave in chaves_aprovadas:
                        # Duplicata → rebaixa para CONDICIONAL
                        resultado["status"]           = "CONDICIONAL"
                        resultado["status_aprovacao"]  = "CONDICIONAL"
                        resultado["stake_multiplier"]  = _STAKE_CONDICIONAL
                        resultado["kelly_quarter"]     = _STAKE_CONDICIONAL / 4.0
                        resultado["motivo"]           += " [REBAIXADO: duplicata ativo+hh_mm+direcao]"
                        condicionais.append(resultado)
                    else:
                        chaves_aprovadas.add(chave)
                        aprovados.append(resultado)
                else:
                    condicionais.append(resultado)
            else:
                reprovados.append(resultado)

        logger.info(
            "[VALIDATOR] %d aprovados | %d condicionais | %d reprovados",
            len(aprovados), len(condicionais), len(reprovados),
        )
        return {
            "aprovados":    aprovados,
            "condicionais": condicionais,
            "reprovados":   reprovados,
        }


# ─────────────────────────────────────────────────────────────────────────────
# HELPER: Filtro V7 — Max Sequência de Hit Consecutivo
# ─────────────────────────────────────────────────────────────────────────────

def _max_consecutive_loss(mined_result: dict) -> int:
    """
    Estima a sequência máxima de Hits (perdas totais no ciclo Gale 2).

    Usa p_hit para calcular: ceil(log(0.01) / log(p_hit)).
    Se p_hit == 0 → sem risco (retorna 0).
    """
    p_hit = float(mined_result.get("p_hit", 0.0))
    if p_hit <= 0.0:
        return 0
    if p_hit >= 1.0:
        return 999
    try:
        k = math.log(0.01) / math.log(p_hit)
        return int(math.ceil(k))
    except (ZeroDivisionError, ValueError):
        return 0
