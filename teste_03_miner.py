"""
TESTE 3: PATTERN MINER (M2) — VERSÃO CHIEF
=============================================
Objetivo: Validar a integridade matemática TOTAL do PatternMiner.

3 Checks obrigatórios:
  1. INVARIANTE: N_WIN_1A + N_GALE1 + N_GALE2 + N_HIT == N_TOTAL (em TODOS)
  2. MELHOR WR: Qual horário mais assertivo para R_100?
  3. GALE SHIFT: n_win_g1 e n_win_g2 estão preenchidos? (se 0 sempre = erro de shift)
"""
import asyncio
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(r"d:\CATALOGADOR DERIV")))

from agente.core.data_loader import DataLoader
from agente.core.hypothesis_generator import HypothesisGenerator
from agente.core.pattern_miner import PatternMiner

import logging
logging.basicConfig(level=logging.INFO, format="%(message)s")

async def test_miner():
    print("="*60)
    print("  TESTE 3: PATTERN MINER (M2) — VERSÃO CHIEF")
    print("="*60)
    
    loader = DataLoader()
    generator = HypothesisGenerator()
    miner = PatternMiner()
    
    ativo = "R_100"
    qtd_velas = 20000 
    
    print(f"\n[1] Baixando {qtd_velas} velas de {ativo} (15 dias)...")
    try:
        candles = await loader.fetch_candles_deriv(ativo, 60, qtd_velas, "1089", days=15)
        registros = loader.parse_candles_to_catalog(candles, ativo)
        df = pd.DataFrame(registros)
        print(f"    [OK] {len(df)} registros montados no schema.")
    except Exception as e:
        print(f"    [ERRO] Falha ao baixar dados: {e}")
        return

    print(f"\n[2] Gerando hipóteses...")
    hypotheses = generator.generate_hypotheses(df, min_edge=0.01, min_n=30)
    print(f"    [OK] {len(hypotheses)} hipóteses prontas.")

    print(f"\n[3] Rodando o Motor de Mineração (V1, V2, V3, V4)...")
    # Filtros frouxos para capturar volume máximo e validar a matemática
    import agente.core.pattern_miner as pm
    pm._MIN_WR_GALE2 = 0.50
    pm._MIN_N = 3
    
    mined_results = miner.mine_all(df, hypotheses)
    
    if not mined_results:
        print("    [!] Nenhuma estratégia passou, mesmo com filtro frouxo.")
        return
        
    print(f"    [OK] {len(mined_results)} estratégias cruas retornadas.\n")
    
    # Contadores por variação
    v_counts = {}
    for r in mined_results:
        v = r.get("variacao", "?")
        v_counts[v] = v_counts.get(v, 0) + 1
    print(f"    Distribuição: {v_counts}")

    # ══════════════════════════════════════════════════════════════════════
    # CHECK 1: INVARIANTE MATEMÁTICO (em TODAS as estratégias)
    # ══════════════════════════════════════════════════════════════════════
    print("\n" + "="*60)
    print("  CHECK 1: INVARIANTE MATEMÁTICO")
    print("  N_WIN_1A + N_GALE1 + N_GALE2 + N_HIT == N_TOTAL")
    print("="*60)
    
    falhas = 0
    total = len(mined_results)
    
    for i, res in enumerate(mined_results):
        n_1a    = res.get("n_win_1a", 0)
        n_g1    = res.get("n_win_g1", 0)
        n_g2    = res.get("n_win_g2", 0)
        n_hit   = res.get("n_hit",    0)
        n_total = res.get("n_total",  0)
        soma    = n_1a + n_g1 + n_g2 + n_hit
        
        if soma != n_total:
            falhas += 1
            if falhas <= 3:  # Mostra no máx 3 exemplos de falha
                print(f"  ❌ Falha #{falhas}: {res.get('variacao','?')} @ {res.get('horario_alvo','?')}")
                print(f"     1ª({n_1a}) + G1({n_g1}) + G2({n_g2}) + HIT({n_hit}) = {soma} ≠ N_TOTAL({n_total})")
    
    if falhas == 0:
        print(f"\n  ✅ SUCESSO: Soma das partes (N) bate com o total em TODOS os {total} grupos.")
    else:
        print(f"\n  ❌ FALHA: {falhas}/{total} violações do invariante!")

    # Mostra 5 exemplos de prova física
    print("\n  📋 Prova física (5 exemplos aleatórios):")
    import random
    samples = random.sample(mined_results, min(5, len(mined_results)))
    for i, res in enumerate(samples, 1):
        n_1a    = res.get("n_win_1a", 0)
        n_g1    = res.get("n_win_g1", 0)
        n_g2    = res.get("n_win_g2", 0)
        n_hit   = res.get("n_hit",    0)
        n_total = res.get("n_total",  0)
        wr      = res.get("win_rate_final", 0)
        hora    = res.get("horario_alvo", "?")
        var     = res.get("variacao", "?")
        print(f"    {i}. {var} @ {hora} | 1ª={n_1a} + G1={n_g1} + G2={n_g2} + HIT={n_hit} = {n_1a+n_g1+n_g2+n_hit} | N={n_total} | WR={wr:.1%}")

    # ══════════════════════════════════════════════════════════════════════
    # CHECK 2: MELHOR WR (Top 5 horários mais assertivos)
    # ══════════════════════════════════════════════════════════════════════
    print("\n" + "="*60)
    print("  CHECK 2: TOP 5 MELHORES WIN RATES")
    print("="*60)
    
    # Ordena por win_rate_final decrescente
    sorted_by_wr = sorted(mined_results, key=lambda x: x.get("win_rate_final", 0), reverse=True)
    
    print(f"\n  {'#':<3} {'Var':<4} {'Horário':<10} {'WR G2':>8} {'N':>5} {'1ª':>4} {'G1':>4} {'G2':>4} {'HIT':>4} {'EV':>8} {'Score':>7}")
    print(f"  {'─'*3} {'─'*4} {'─'*10} {'─'*8} {'─'*5} {'─'*4} {'─'*4} {'─'*4} {'─'*4} {'─'*8} {'─'*7}")
    
    for i, res in enumerate(sorted_by_wr[:5], 1):
        var     = res.get("variacao", "?")
        hora    = res.get("horario_alvo", "?")
        wr      = res.get("win_rate_final", 0)
        n       = res.get("n_total", 0)
        n_1a    = res.get("n_win_1a", 0)
        n_g1    = res.get("n_win_g1", 0)
        n_g2    = res.get("n_win_g2", 0)
        n_hit   = res.get("n_hit", 0)
        ev      = res.get("ev_final", 0)
        score   = res.get("score_ponderado", 0)
        print(f"  {i:<3} {var:<4} {hora:<10} {wr:>7.1%} {n:>5} {n_1a:>4} {n_g1:>4} {n_g2:>4} {n_hit:>4} {ev:>+8.4f} {score:>7.4f}")

    # ══════════════════════════════════════════════════════════════════════
    # CHECK 3: GALE SHIFT (n_win_g1 e n_win_g2 preenchidos?)
    # ══════════════════════════════════════════════════════════════════════
    print("\n" + "="*60)
    print("  CHECK 3: GALE SHIFT (G1 e G2 preenchidos?)")
    print("="*60)
    
    total_g1_sum = sum(r.get("n_win_g1", 0) for r in mined_results)
    total_g2_sum = sum(r.get("n_win_g2", 0) for r in mined_results)
    total_hit_sum = sum(r.get("n_hit", 0) for r in mined_results)
    total_1a_sum = sum(r.get("n_win_1a", 0) for r in mined_results)
    total_n_sum  = sum(r.get("n_total", 0) for r in mined_results)
    
    # Quantas estratégias têm G1 > 0?
    strats_com_g1 = sum(1 for r in mined_results if r.get("n_win_g1", 0) > 0)
    strats_com_g2 = sum(1 for r in mined_results if r.get("n_win_g2", 0) > 0)
    strats_com_hit = sum(1 for r in mined_results if r.get("n_hit", 0) > 0)
    
    print(f"\n  Soma global de todas as {total} estratégias:")
    print(f"    Total 1ª entrada:  {total_1a_sum:>6}")
    print(f"    Total Gale 1:      {total_g1_sum:>6}  ({strats_com_g1}/{total} estratégias com G1 > 0)")
    print(f"    Total Gale 2:      {total_g2_sum:>6}  ({strats_com_g2}/{total} estratégias com G2 > 0)")
    print(f"    Total HIT (loss):  {total_hit_sum:>6}  ({strats_com_hit}/{total} estratégias com HIT > 0)")
    print(f"    ───────────────────────────")
    print(f"    SOMA GERAL:        {total_1a_sum + total_g1_sum + total_g2_sum + total_hit_sum:>6}")
    print(f"    N TOTAL GERAL:     {total_n_sum:>6}")
    
    if total_g1_sum == 0:
        print(f"\n  ❌ ERRO DE SHIFT: Gale 1 está SEMPRE 0! O cálculo de proxima_2 pode estar errado.")
    else:
        print(f"\n  ✅ Gale 1 está PREENCHIDO ({total_g1_sum} wins via G1). Shift correto!")
        
    if total_g2_sum == 0:
        print(f"  ❌ ERRO DE SHIFT: Gale 2 está SEMPRE 0! O cálculo de proxima_3 pode estar errado.")
    else:
        print(f"  ✅ Gale 2 está PREENCHIDO ({total_g2_sum} wins via G2). Shift correto!")
    
    if total_hit_sum == 0:
        print(f"  ⚠️ ALERTA: HIT está SEMPRE 0 — pode ser que todos ganham (improvável) ou erro de cálculo.")
    else:
        print(f"  ✅ HIT (loss) está PREENCHIDO ({total_hit_sum} hits totais). Cálculo realista!")

    # ══════════════════════════════════════════════════════════════════════
    # CHECK EXTRA: Anti-anomalia (WR 100%)
    # ══════════════════════════════════════════════════════════════════════
    anomalias = [r for r in mined_results if r.get("win_rate_final", 0) >= 1.0]
    if anomalias:
        print(f"\n  ❌ ALERTA: {len(anomalias)} estratégias com WR >= 100%!")
    else:
        print(f"\n  ✅ Zero estratégias com WR 100% (anti-overfitting OK).")

    # ══════════════════════════════════════════════════════════════════════
    # RESUMO FINAL
    # ══════════════════════════════════════════════════════════════════════
    print("\n" + "="*60)
    print("  RESUMO FINAL DO TESTE 3")
    print("="*60)
    check1 = "✅" if falhas == 0 else "❌"
    check2_wr = sorted_by_wr[0].get("win_rate_final", 0) if sorted_by_wr else 0
    check2_hora = sorted_by_wr[0].get("horario_alvo", "?") if sorted_by_wr else "?"
    check3_ok = total_g1_sum > 0 and total_g2_sum > 0
    check3 = "✅" if check3_ok else "❌"
    check4 = "✅" if not anomalias else "❌"
    
    print(f"  {check1} Check 1 (Invariante):  {total - falhas}/{total} grupos OK")
    print(f"  🏆 Check 2 (Melhor WR):  {check2_wr:.1%} @ {check2_hora}")
    print(f"  {check3} Check 3 (Gale Shift):  G1={total_g1_sum} | G2={total_g2_sum}")
    print(f"  {check4} Check 4 (Anti-100%):   {len(anomalias)} anomalias")
    print("="*60)

if __name__ == "__main__":
    asyncio.run(test_miner())
