"""
signal_injector.py — Injeta sinais do IQ Lake em iq_quant_signals
Roda a cada minuto no VPS via cron ou loop.
Lê config_iq_lake.json → filtra hh_mm atual → INSERT em iq_quant_signals

FIX: Anti-duplicata — verifica se já existe sinal para o mesmo ativo+timestamp
     antes de inserir. Evita 3 sinais idênticos por minuto.
"""
import json, time, os, requests
from datetime import datetime, timezone
from pathlib import Path

SUPABASE_URL = "https://ypqekkkrfklaqlzhkbwg.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_HFT_KEY")
CONFIG_PATH  = Path(__file__).parent / "config_iq_lake.json"

HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "return=minimal",
}


def _signal_already_exists(ativo: str, ts_sinal: int) -> bool:
    """Verifica se já existe sinal CONFIRMED para este ativo+timestamp.
    Anti-duplicata: evita INSERT de sinais idênticos."""
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/iq_quant_signals",
            params={
                "ativo":           f"eq.{ativo}",
                "timestamp_sinal": f"eq.{ts_sinal}",
                "status":          "eq.CONFIRMED",
                "select":          "id",
                "limit":           "1",
            },
            headers=HEADERS,
            timeout=10,
        )
        if r.status_code == 200 and r.json():
            return True
    except Exception as e:
        print(f"[INJECTOR] Erro ao checar duplicata: {e}")
    return False


def inject():
    now_utc  = datetime.now(timezone.utc)
    hh_mm    = now_utc.strftime("%H:%M")
    ts_sinal = int(now_utc.timestamp())

    # Verifica se o arquivo existe antes de ler para evitar FileNotFound
    if not CONFIG_PATH.exists():
        print(f"[INJECTOR] Erro: {CONFIG_PATH} não encontrado.")
        return

    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"[INJECTOR] Erro ao ler JSON: {e}")
        return

    # Filtra estratégias do minuto atual com status APROVADO ou CONDICIONAL
    sinais = [
        v for v in config.values()
        if v.get("hh_mm") == hh_mm and v.get("status") in ("APROVADO", "CONDICIONAL")
    ]

    if not sinais:
        print(f"[INJECTOR] {hh_mm} — nenhuma estratégia aprovada para agora")
        return

    # Ordena por ev_g2 desc, pega o melhor
    sinais.sort(key=lambda x: x.get("ev_g2", 0), reverse=True)
    best = sinais[0]

    ativo = best.get("ativo")

    # ── ANTI-DUPLICATA: checa se já existe sinal para este ativo+timestamp ──
    if _signal_already_exists(ativo, ts_sinal):
        print(f"[INJECTOR] ⏭️ Sinal já existe para {hh_mm} | {ativo} — pulando duplicata")
        return

    payload = {
        "ativo":            ativo,
        "estrategia":       f"IQ_LAKE_{best.get('status')}",
        "direcao":          best.get("direcao"),
        "p_win_historica":  best.get("p_win_g2"),
        "status":           "CONFIRMED",  # FIX: era "confirmed" (minúsculo), worker busca "CONFIRMED"
        "client_id":        "GLOBAL",      # FIX: era omitido, worker filtra por client_id in.(GLOBAL,<id>)
        "timestamp_sinal":  ts_sinal,
        "contexto": json.dumps({
            "ev_g2":    best.get("ev_g2"),
            "p_win_1a": best.get("p_win_1a"),
            "n_total":  best.get("n_total"),
            "n_hit":    best.get("n_hit"),
            "fonte":    "IQ_LAKE_V1",
        }),
    }

    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/iq_quant_signals",
        json=payload,
        headers=HEADERS,
    )

    if r.status_code in (200, 201):
        print(f"[INJECTOR] ✅ {hh_mm} | {ativo} {best.get('direcao')} | WR={best.get('p_win_g2', 0):.1%} EV={best.get('ev_g2', 0):+.4f}")
    else:
        print(f"[INJECTOR] ❌ Erro {r.status_code}: {r.text}")

if __name__ == "__main__":
    print("[INJECTOR] Iniciando loop — injetando sinais a cada 60s")
    while True:
        try:
            inject()
        except Exception as e:
            print(f"[INJECTOR] ERRO GERAL: {e}")
        time.sleep(60)
