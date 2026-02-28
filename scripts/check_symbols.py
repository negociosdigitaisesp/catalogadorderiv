import asyncio
import json
import websockets
import os

async def main():
    app_id = os.getenv("DERIV_APP_ID", "1089") # Default public app_id
    url = f"wss://ws.binaryws.com/websockets/v3?app_id={app_id}"
    
    async with websockets.connect(url) as ws:
        req = {
            "active_symbols": "brief",
            "product_type": "basic"
        }
        await ws.send(json.dumps(req))
        resp_raw = await asyncio.wait_for(ws.recv(), timeout=10)
        resp = json.loads(resp_raw)
        
        symbols = resp.get("active_symbols", [])
        synthetic_symbols = [s["symbol"] for s in symbols if s.get("market") == "synthetic_index"]
        
        print("Valid Synthetic Indices:")
        for s in synthetic_symbols:
            if "BOOM" in s or "CRASH" in s or "R_" in s:
                print(s)

if __name__ == "__main__":
    asyncio.run(main())
