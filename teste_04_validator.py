"""
TESTE 4: STRATEGY VALIDATOR (M3) — Funil de EV & Qualidade de Entrada
======================================================================
Valida os 4 cortes + Regra de Ouro + Contenção + Trava Anti-Duplicata.

Mock Data:
  1. R_100 Elite     → APROVADO    (EV=0.15, WR=95%, P1A=60%, N=30)
  2. R_50 Condicional → CONDICIONAL (EV=0.08, WR=91%, P1A=40%, N=25) ← P1A < 55%
  3. R_25 Low WR     → REPROVADO   (WR=85% < 88%)
  4. R_10 Low N      → REPROVADO   (N=5 < 15)
  5. R_75 EV Zero    → REPROVADO   (EV=-0.05 <= 0)
  6. R_100 Duplicata → CONDICIONAL  (mesma chave que #1, rebaixada anti-duplicata)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(r"d:\CATALOGADOR DERIV")))

from agente.core.strategy_validator import StrategyValidator

import logging
logging.basicConfig(level=logging.INFO, format="%(message)s")


def make_mock(ativo, hh_mm, direcao, variacao, wr, ev, p_1a, n):
    """Cria um mock de mined_result compatível com o PatternMiner."""
    p_gale1 = min(p_1a + 0.15, wr)
    p_gale2 = wr
    p_hit   = 1.0 - wr
    return {
        "variacao":       variacao,
        "win_rate_final": wr,
        "ev_final":       ev,
        "n_total":        n,
        "n_test":         n,
        "n_win_1a":       int(n * p_1a),
        "n_win_g1":       int(n * 0.15),
        "n_win_g2":       int(n * (wr - p_1a - 0.15)) if wr > p_1a + 0.15 else 0,
        "n_hit":          int(n * p_hit),
        "p_1a":           p_1a,
        "p_gale1":        p_gale1,
        "p_gale2":        p_gale2,
        "p_hit":          p_hit,
        "score_ponderado": wr,
        "horario_alvo":   hh_mm,
        "hypothesis": {
            "ativo":    ativo,
            "contexto": {"hh_mm": hh_mm, "dia_semana": "SEG"},
            "direcao":  direcao,
        },
    }


def test_validator():
    print("=" * 58)
    print("  TESTE 4: STRATEGY VALIDATOR (M3) — Funil de EV")
    print("=" * 58)

    validator = StrategyValidator()

    # ── Mocks ────────────────────────────────────────────────────────────
    mocks = [
        # 1. Elite (deve ser APROVADO)
        make_mock("R_100", "14:00", "CALL", "V1", wr=0.95, ev=0.15, p_1a=0.60, n=30),
        # 2. Lucrativo mas P1A baixo (CONDICIONAL)
        make_mock("R_50",  "15:00", "PUT",  "V1", wr=0.91, ev=0.08, p_1a=0.40, n=25),
        # 3. WR abaixo de 88% (REPROVADO)
        make_mock("R_25",  "16:00", "CALL", "V2", wr=0.85, ev=0.05, p_1a=0.50, n=40),
        # 4. N insuficiente (REPROVADO)
        make_mock("R_10",  "17:00", "CALL", "V1", wr=0.98, ev=0.20, p_1a=0.70, n=5),
        # 5. EV negativo (REPROVADO)
        make_mock("R_75",  "18:00", "PUT",  "V4", wr=0.90, ev=-0.05, p_1a=0.55, n=20),
        # 6. Duplicata da #1 (deve ser rebaixada para CONDICIONAL)
        make_mock("R_100", "14:00", "CALL", "V4", wr=0.96, ev=0.18, p_1a=0.65, n=28),
    ]

    print(f"\n[1] Injetando {len(mocks)} estratégias no Validador...\n")
    batch = validator.validate_batch(mocks)

    aprovados    = batch["aprovados"]
    condicionais = batch["condicionais"]
    reprovados   = batch["reprovados"]
    
    print(f"\n[2] Resultado: {len(aprovados)} aprovados | {len(condicionais)} condicionais | {len(reprovados)} reprovados\n")

    # ── Detalhes ────────────────────────────────────────────────────────
    print("[3] Detalhes de TODAS as classificações:")
    all_results = (
        [(r, "🟢") for r in aprovados] +
        [(r, "🟡") for r in condicionais] +
        [(r, "🔴") for r in reprovados]
    )
    for r, icon in all_results:
        mr  = r["mined_result"]
        hyp = mr.get("hypothesis", {})
        print(f"  {icon} {hyp.get('ativo','?')} @ {hyp.get('contexto',{}).get('hh_mm','?')} "
              f"| WR={r['win_gale2_rate']:.1%} | EV={r['ev_gale2']:+.4f} "
              f"| P1A={r['win_1a_rate']:.1%} | N={mr.get('n_total',0)} "
              f"| Status={r['status']} | {r['motivo']}")

    # ── Asserts ──────────────────────────────────────────────────────────
    print(f"\n[4] Conferência dos Asserts:")

    # Assert 1: Exatamente 1 aprovado (R_100 Elite)
    assert len(aprovados) == 1, f"Esperado 1 aprovado, obteve {len(aprovados)}"
    assert aprovados[0]["mined_result"]["hypothesis"]["ativo"] == "R_100"
    assert aprovados[0]["stake_multiplier"] == 1.0
    print(f"  ✅ 1 APROVADO (R_100 Elite, Stake 1.0)")

    # Assert 2: Exatamente 2 condicionais (R_50 + R_100 Duplicata)
    assert len(condicionais) == 2, f"Esperado 2 condicionais, obteve {len(condicionais)}"
    print(f"  ✅ 2 CONDICIONAIS (R_50 P1A baixo + R_100 Duplicata rebaixada)")
    # A duplicata deve ter motivo com "REBAIXADO"
    dup = [c for c in condicionais if "REBAIXADO" in c["motivo"]]
    assert len(dup) == 1, "Duplicata deveria ter sido rebaixada!"
    print(f"  ✅ Trava anti-duplicata funcionou: '{dup[0]['motivo'][:60]}...'")

    # Assert 3: Exatamente 3 reprovados
    assert len(reprovados) == 3, f"Esperado 3 reprovados, obteve {len(reprovados)}"
    motivos = [r["motivo"] for r in reprovados]
    assert any("85" in m or "88" in m for m in motivos), "Falhou assert WR < 88%"
    assert any("N=" in m and "15" in m for m in motivos), "Falhou assert N < 15"
    assert any("EV" in m and "positivo" in m for m in motivos), "Falhou assert EV <= 0"
    print(f"  ✅ 3 REPROVADOS (WR<88%, N<15, EV<=0)")

    # Assert 4: Total bate
    total = len(aprovados) + len(condicionais) + len(reprovados)
    assert total == len(mocks), f"Total {total} != mocks {len(mocks)}"
    print(f"  ✅ Total consistente: {total}/{len(mocks)}")

    print(f"\n{'='*58}")
    print(f"  TESTE 4 CONCLUÍDO COM SUCESSO — FUNIL DE EV VALIDADO!")
    print(f"{'='*58}")


if __name__ == "__main__":
    test_validator()
