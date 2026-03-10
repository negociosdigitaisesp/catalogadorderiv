import os
import sys
import time
import httpx
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
load_dotenv()

SUPABASE_HFT_URL = os.getenv("SUPABASE_HFT_URL") or os.getenv("SUPABASE_URL")
SUPABASE_HFT_KEY = os.getenv("SUPABASE_HFT_KEY") or os.getenv("SUPABASE_KEY")

HEADERS = {
    "apikey": SUPABASE_HFT_KEY,
    "Authorization": f"Bearer {SUPABASE_HFT_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal",
}

CLIENT_ID = "teste_start_stop"

def set_running(val: bool):
    print(f">> Setting {CLIENT_ID} is_running={val}")
    r = httpx.patch(
        f"{SUPABASE_HFT_URL}/rest/v1/bot_clients",
        headers=HEADERS,
        params={"client_id": f"eq.{CLIENT_ID}"},
        json={"is_running": val}
    )
    r.raise_for_status()

# 1. Start with it OFF
set_running(False)
print("Waiting 5s to ensure executor saw it OFF...")
time.sleep(5)

# 2. Turn ON
set_running(True)
print("Turned ON. Supervisor should start worker within ~5s. Watch executor logs!")
time.sleep(7)

# 3. Turn OFF
set_running(False)
print("Turned OFF. Worker should shutdown on next cycle.")
