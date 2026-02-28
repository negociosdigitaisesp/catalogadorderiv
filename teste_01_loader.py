import asyncio
import sys
from pathlib import Path
import pandas as pd

# Ajustar path para importa o pacote
sys.path.insert(0, str(Path(r"d:\CATALOGADOR DERIV")))

from agente.core.data_loader import DataLoader

async def test_loader():
    print("="*50)
    print(" TESTE 1: DATA LOADER (M0) ")
    print("="*50)
    
    loader = DataLoader()
    ativo_teste = "R_25"
    qtd_velas = 1000
    app_id = "1089" # App ID genérico de teste Deriv
    
    print(f"[1] Baixando {qtd_velas} velas M1 recentes de {ativo_teste} da Deriv...")
    try:
        # Puxa poucos dados só para não demorar
        candles = await loader.fetch_candles_deriv(ativo_teste, 60, qtd_velas, app_id, days=1)
        print(f"[OK] {len(candles)} velas baixadas.")
    except Exception as e:
        print(f"[ERRO] Falha ao conectar na Deriv: {e}")
        return

    print("\n[2] Passando as velas pelo `parse_candles_to_catalog` (Mapeamento de Schema)...")
    registros = loader.parse_candles_to_catalog(candles, ativo_teste)
    
    df = pd.DataFrame(registros)
    
    print("\n[3] Inspecionando o Schema V2 gerado:")
    colunas_chave = ["hh_mm", "cor_atual", "mhi_seq", "proxima_1", "proxima_2", "proxima_3", "tendencia_m5"]
    print(df[colunas_chave].tail(10).to_string())
    
    print("\n[4] Teste de Segurança (NaNs em próximas velas):")
    nans = df[["proxima_1", "proxima_2", "proxima_3"]].isna().sum().sum()
    if nans == 0:
        print("  ✅ Sucesso: 0 Valores NaN! Substituídos corretamente por '?'.")
    else:
        print(f"  ❌ FALHA: Encontrados {nans} valores NaN ou sujos.")
        
    qtd_interrogacao = (df[["proxima_1", "proxima_2", "proxima_3"]] == "?").sum().to_dict()
    print(f"  Velhas cegas (no final do DF, sem futuro): {qtd_interrogacao}")

    print("\n[5] Teste de MHI (Velas no começo sem histórico):")
    qtd_mhi_vazio = (df["mhi_seq"] == "?-?-?").sum()
    print(f"  Velas com mhi_seq='?-?-?': {qtd_mhi_vazio} (deve ser 2, que são as primeiras)")
    
    print("\n="*50)
    print(" TESTE CONCLUÍDO. Se estiver tudo certo, avance pro Teste 2 (Gerador).")
    print("="*50)

if __name__ == "__main__":
    asyncio.run(test_loader())
