import asyncio
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(r"d:\CATALOGADOR DERIV")))

from agente.core.data_loader import DataLoader
from agente.core.hypothesis_generator import HypothesisGenerator

async def test_generator():
    print("="*50)
    print(" TESTE 2: HYPOTHESIS GENERATOR (M1) ")
    print("="*50)
    
    loader = DataLoader()
    generator = HypothesisGenerator()
    ativo = "R_50"
    qtd_velas = 5000
    
    print(f"[1] Baixando {qtd_velas} velas de {ativo} para ter massa de dados inicial...")
    try:
        candles = await loader.fetch_candles_deriv(ativo, 60, qtd_velas, "1089", days=1)
        registros = loader.parse_candles_to_catalog(candles, ativo)
        df_teste = pd.DataFrame(registros)
        print(f"[OK] {len(df_teste)} registros montados no schema.")
    except Exception as e:
        print(f"[ERRO] Falha ao baixar dados: {e}")
        return

    print("\n[2] Calculando baseline do ativo (HypothesisGenerator.compute_base_frequencies)...")
    base_stats = generator.compute_base_frequencies(df_teste)
    p_win_ativo = base_stats["por_ativo"][ativo]["p_win"]
    print(f"  P(WIN) Global ({ativo}): {p_win_ativo:.2%}")
    
    print("\n[3] Gerando Hipóteses Contextuais...")
    # Usando min_n=30 e min_edge=0.01 para forçar encontrar alguma coisa em apenas 5000 velas
    hypotheses = generator.generate_hypotheses(df_teste, min_edge=0.02, min_n=30)
    
    if not hypotheses:
        print("  [!] Nenhuma hipótese encontrada com Edge > 2% e N > 30 nesta amostra pequena.")
    else:
        print(f"  [OK] Encontradas {len(hypotheses)} hipóteses!")
        
        # O top 5 
        print("\n[4] TOP 3 Hipóteses (ordenadas por Prioridade):")
        for i, h in enumerate(hypotheses[:3], 1):
            ctx = ", ".join(f"{k}={v}" for k, v in h["contexto"].items())
            print(f"  {i}. {h['direcao']} | Contexto: [{ctx}]")
            print(f"     N={h['n_amostras']} | WR={h['p_win_condicional']:.2%} | Edge={h['edge_bruto']:+.2%} | Prio={h['prioridade']:.4f}")

        # Validando as regras do PRD
        print("\n[5] Validando Regra de Ouro (Win Rate < 100%):")
        invalidas = [h for h in hypotheses if h["p_win_condicional"] >= 1.0]
        if not invalidas:
            print("  ✅ Sucesso: Nenhuma hipótese com 100% de acerto (p_win_cond >= 1.0) passou.")
        else:
            print(f"  ❌ FALHA: Fizeram {len(invalidas)} hipóteses com 100% absurdas passarem.")
            
        print("\n[6] Validando se todas bateram o Edge Mínimo (2%):")
        abaixo = [h for h in hypotheses if h["edge_bruto"] < 0.02]
        if not abaixo:
            print("  ✅ Sucesso: Todas as hipóteses têm edge > 2%.")
        else:
            print(f"  ❌ FALHA: Encontradas {len(abaixo)} hipóteses sem o edge exigido.")
            
    print("\n="*50)
    print(" TESTE CONCLUÍDO. Avance pro Teste 3 se os ✅ Sucessos aparecerem.")
    print("="*50)

if __name__ == "__main__":
    asyncio.run(test_generator())
