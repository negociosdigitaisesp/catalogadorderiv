"""
Script para limpar a tabela antiga de candles.
Rodar: python scripts/limpar_db.py
"""

import os
import sqlite3
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def limpar_banco(db_path="catalog/catalog.db"):
    db_file = Path(db_path)
    if not db_file.exists():
        logger.info("Banco %s não existe. Nada a limpar.", db_file)
        return

    # Opção 1: Apagar o arquivo inteiro
    try:
        os.remove(db_file)
        logger.info("✅ Arquivo do banco de dados removido com sucesso: %s", db_file)
    except Exception as e:
        logger.error("❌ Erro ao remover o banco: %s", e)
        
    # Quando o agente rodar novamente, ele criará um novo banco e tabelas zeradas.

if __name__ == "__main__":
    limpar_banco()
