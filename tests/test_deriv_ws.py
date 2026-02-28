"""
tests/test_deriv_ws.py

Testa apenas a conexao WebSocket pura com a API da Deriv
para identificar se o IP está bloqueado, porta 443 filtrada,
ou app_id inválido.
"""

import asyncio
import json
import logging
import sys

import websockets

logging.basicConfig(level=logging.DEBUG)

APP_ID = "85515"  # Tentar com o app_id do projeto
# APP_ID = "1089"   # Tentar com o app_id publico da Deriv caso falhe

async def test_deriv():
    url = f"wss://ws.binaryws.com/websockets/v3?app_id={APP_ID}"
    print(f"[*] Tentando conectar em: {url}")
    
    try:
        async with websockets.connect(
            url,
            ping_interval=20,
            ping_timeout=30,
            close_timeout=10,
        ) as ws:
            print("[+] Conectado com sucesso!")
            
            payload = json.dumps({"ticks": "R_10", "subscribe": 1})
            print(f"[*] Enviando payload: {payload}")
            await ws.send(payload)
            
            print("[*] Aguardando resposta...")
            # Pega as primeiras mensagens
            for _ in range(3):
                msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                print(f"[RX] {msg}")
                
            print("[+] Teste concluido com sucesso.")
            
    except asyncio.TimeoutError:
        print("[-] ERRO: Timeout aguardando mensagem!")
    except Exception as e:
        print(f"[-] ERRO FATAL: {e}")

if __name__ == "__main__":
    asyncio.run(test_deriv())
