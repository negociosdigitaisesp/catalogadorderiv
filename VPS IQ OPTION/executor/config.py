import os

SUPABASE_HFT_URL = "https://ypqekkkrfklaqlzhkbwg.supabase.co"
SUPABASE_HFT_KEY = os.getenv("SUPABASE_HFT_KEY")

IQ_PROXY = os.getenv("IQ_PROXY")

POLL_INTERVAL_SEC      = 10
SIGNAL_WINDOW_SEC      = 90    # descarta sinais mais antigos que 90s
SIGNAL_FETCH_LIMIT     = 1     # evita rajada: processa 1 sinal novo por ciclo
RISK_CONFIG_TTL_SEC    = 5     # aplica alteracoes de stake/stop quase em tempo real
MAX_CLIENTS            = 50
RECONNECT_ATTEMPTS     = -1    # -1 = infinito
HEARTBEAT_INTERVAL_SEC = 10
MAX_RETRIES            = 3
RETRY_BASE_DELAY       = 2     # segundos (backoff: 2, 4, 8)

assert SUPABASE_HFT_KEY, "SUPABASE_HFT_KEY não definida no ambiente"
