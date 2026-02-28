"""
Script de diagnostico para testar insercao direta no Supabase e verificar schema.
Isso ajuda a descobrir por que o StrategyWriter nao esta inserindo.
"""
import sys
import json
import datetime

def checar_banco():
    try:
        import psycopg2
    except ImportError:
        print("Instalando psycopg2-binary...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "psycopg2-binary", "-q"])
        import psycopg2

    conn_str = "postgresql://postgres:1CIwYGQv09MUQA@db.ypqekkkrfklaqlzhkbwg.supabase.co:5432/postgres"
    print("Conectando ao banco de dados...")
    
    try:
        conn = psycopg2.connect(conn_str, sslmode="require")
        cur = conn.cursor()
        print("✅ Conexao com Supabase (PostgreSQL) bem-sucedida!")
        
        # 1. Checa as colunas
        cur.execute("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'hft_oracle_results' 
            ORDER BY ordinal_position
        """)
        cols = cur.fetchall()
        col_names = [c[0] for c in cols]
        print("\n📋 Colunas atuais em `hft_oracle_results`:")
        for cname, ctype in cols:
            print(f"  - {cname:<20} {ctype}")
            
        # Verifica colunas da migracao 005
        novas_colunas = ['variacao_estrategia', 'n_win_1a', 'n_win_g1', 'n_win_g2', 'n_hit', 'n_total']
        faltando = [c for c in novas_colunas if c not in col_names]
        
        if faltando:
            print(f"\n❌ ERRO CRÍTICO: As seguintes colunas da migração 005 estão faltando: {faltando}")
            print("Isso explica por que o insert falha (o Supabase API rejeita o payload em silencio)")
            print("Solução: rode `python scripts/run_migration.py` e garanta que dê sucesso.")
        else:
            print("\n✅ Todas as colunas novas da migração 005 estão presentes.")
            
    except Exception as e:
        print(f"❌ Erro ao conectar no Postgres via psycopg2: {e}")
    finally:
        if 'cur' in locals(): cur.close()
        if 'conn' in locals(): conn.close()

    # 2. Testa um insert manual usando supabase-py (HTTP API REST - Não depende da porta 5432!)
    print("\n🔄 Testando Inserçao via REST API (como o StrategyWriter faz)...")
    try:
        from supabase import create_client
        # Pega as chaves do .env local
        import os
        from dotenv import load_dotenv
        load_dotenv()
        
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        
        if not url or not key:
            print("❌ ERRO: SUPABASE_URL ou SUPABASE_KEY nao encontrados no .env!")
            return
            
        sb_client = create_client(url, key)
        
        payload = {
            # Identificação
            "ativo": "R_100",
            "estrategia": "GRADE_G2_1430_SEG",
            "strategy_id": "T1430_SEG_R100_G2",
            # Métricas de performance
            "win_rate": 0.95,
            "n_amostral": 15,
            "ev_real": 0.5,
            "edge_vs_be": 0.4095,
            "status": "APROVADO",
            "sizing_override": 1.0,
            # Colunas de auditoria
            "variacao_estrategia": "V1",
            "n_win_1a": 10,
            "n_win_g1": 3,
            "n_win_g2": 2,
            "n_hit": 0,
            "n_total": 15,
            # JSONB
            "config_otimizada": {
                "tipo": "HORARIO",
                "hh_mm": "14:30",
                "dia_semana": 0,
                "direcao": "CALL",
                "max_gale": 2,
                "variacao": "V1",
                "win_1a_rate": 0.66,
                "win_gale1_rate": 0.20,
                "win_gale2_rate": 0.13,
                "hit_rate": 0.0,
            },
            "last_update": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        
        # Tenta inserir
        res = sb_client.table("hft_oracle_results").upsert(
            payload, on_conflict="ativo,estrategia,strategy_id"
        ).execute()
        
        print("✅ INSERT Supabase (REST) executado com sucesso! Resposta da API:")
        print(res)
        
    except Exception as e:
        print(f"\n❌ ERRO NA API REST DO SUPABASE (Este é o motivo da falha geral!):")
        print(e)


if __name__ == "__main__":
    checar_banco()
