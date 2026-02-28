"""
Gera preview HTML da catalogação grade_horaria.
Uso: python preview_catalogacao.py catalogacao/grade_horaria_2026-02-27_182938.json
"""
import json, sys, os
from pathlib import Path
from collections import defaultdict

def gerar_html(json_path: str):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    info = data.get("_identificacao", {})
    grade = data.get("grade_horaria", [])

    # Agrupa por ativo
    por_ativo = defaultdict(list)
    for s in grade:
        por_ativo[s.get("ativo", "?")].append(s)

    # Stats por ativo
    stats = {}
    for ativo, strats in sorted(por_ativo.items()):
        apr = [s for s in strats if s.get("status") == "APROVADO"]
        cond = [s for s in strats if s.get("status") == "CONDICIONAL"]
        avg_wr = sum(s.get("win_rate_g2", 0) for s in strats) / len(strats) if strats else 0
        avg_ev = sum(s.get("ev_gale2", 0) for s in strats) / len(strats) if strats else 0
        best = max(strats, key=lambda s: s.get("win_rate_g2", 0)) if strats else {}
        stats[ativo] = {"total": len(strats), "apr": len(apr), "cond": len(cond),
                        "avg_wr": avg_wr, "avg_ev": avg_ev, "best": best}

    # Gera HTML
    ativo_cards = ""
    ativo_tabs = ""
    ativo_sections = ""

    for ativo in sorted(por_ativo.keys()):
        s = stats[ativo]
        strats = sorted(por_ativo[ativo], key=lambda x: -x.get("win_rate_g2", 0))
        safe_id = ativo.replace("_", "").replace(" ", "")

        ativo_tabs += f'<button class="tab-btn" onclick="showAtivo(\'{safe_id}\')" id="tab-{safe_id}">{ativo}</button>\n'

        ativo_cards += f'''
        <div class="stat-card">
            <div class="stat-label">{ativo}</div>
            <div class="stat-value">{s["total"]}</div>
            <div class="stat-sub">✅ {s["apr"]} | ⚠️ {s["cond"]}</div>
        </div>'''

        rows = ""
        for st in strats:
            status = st.get("status", "?")
            cls = "row-approved" if status == "APROVADO" else "row-conditional"
            badge = '<span class="badge-approved">APROVADO</span>' if status == "APROVADO" else '<span class="badge-conditional">CONDICIONAL</span>'
            wr = st.get("win_rate_g2", 0)
            ev = st.get("ev_gale2", 0)
            p1a = st.get("win_1a_rate", 0)
            wr_bar_w = min(wr * 100, 100)
            p1a_cls = "p1a-good" if p1a >= 0.55 else "p1a-warn"

            rows += f'''<tr class="{cls}">
                <td>{st.get("hh_mm","?")}</td>
                <td><span class="dir-{st.get('direcao','').lower()}">{st.get("direcao","?")}</span></td>
                <td><span class="var-tag">{st.get("variacao","?")}</span></td>
                <td><div class="wr-cell"><div class="wr-bar" style="width:{wr_bar_w}%"></div><span>{wr:.1%}</span></div></td>
                <td class="{'ev-pos' if ev > 0 else 'ev-neg'}">{ev:+.4f}</td>
                <td class="{p1a_cls}">{p1a:.0%}</td>
                <td class="num">{st.get("n_win_1a",0)}</td>
                <td class="num">{st.get("n_win_g1",0)}</td>
                <td class="num">{st.get("n_win_g2",0)}</td>
                <td class="num hit">{st.get("n_hit",0)}</td>
                <td class="num">{st.get("n_total",0)}</td>
                <td>{badge}</td>
                <td>{st.get("stake",0):.1f}x</td>
            </tr>'''

        ativo_sections += f'''
        <div class="ativo-section" id="sec-{safe_id}" style="display:none">
            <div class="section-header">
                <h2>📊 {ativo}</h2>
                <div class="section-stats">
                    <span class="pill green">{s["apr"]} Aprovadas</span>
                    <span class="pill yellow">{s["cond"]} Condicionais</span>
                    <span class="pill blue">WR Médio: {s["avg_wr"]:.1%}</span>
                    <span class="pill purple">EV Médio: {s["avg_ev"]:+.4f}</span>
                </div>
            </div>
            <div class="table-wrap">
            <table>
                <thead><tr>
                    <th>Hora</th><th>Dir</th><th>Var</th><th>WR G2</th><th>EV</th>
                    <th>P1ª</th><th>1ª</th><th>G1</th><th>G2</th><th>HIT</th><th>N</th>
                    <th>Status</th><th>Stake</th>
                </tr></thead>
                <tbody>{rows}</tbody>
            </table>
            </div>
        </div>'''

    html = f'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Oracle Quant — Catalogação {info.get("data_catalogacao","")}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root {{
    --bg: #0a0e17; --surface: #111827; --surface2: #1e293b;
    --border: #1e293b; --text: #e2e8f0; --text2: #94a3b8;
    --green: #10b981; --green-bg: rgba(16,185,129,.12);
    --yellow: #f59e0b; --yellow-bg: rgba(245,158,11,.12);
    --red: #ef4444; --blue: #3b82f6; --purple: #8b5cf6;
    --accent: #06b6d4;
}}
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:'Inter',sans-serif; background:var(--bg); color:var(--text); min-height:100vh; }}
.container {{ max-width:1400px; margin:0 auto; padding:24px; }}

/* Header */
.header {{ background:linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%); border:1px solid var(--border);
    border-radius:16px; padding:32px; margin-bottom:24px; }}
.header h1 {{ font-size:28px; font-weight:700; background:linear-gradient(90deg,#06b6d4,#8b5cf6);
    -webkit-background-clip:text; -webkit-text-fill-color:transparent; margin-bottom:8px; }}
.header .sub {{ color:var(--text2); font-size:14px; }}
.header .meta {{ display:flex; gap:24px; margin-top:16px; flex-wrap:wrap; }}
.header .meta span {{ background:var(--surface2); padding:6px 14px; border-radius:8px; font-size:13px;
    font-family:'JetBrains Mono',monospace; }}

/* Stats Grid */
.stats-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(140px,1fr)); gap:12px; margin-bottom:24px; }}
.stat-card {{ background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:16px; text-align:center;
    transition:transform .2s,border-color .2s; cursor:pointer; }}
.stat-card:hover {{ transform:translateY(-2px); border-color:var(--accent); }}
.stat-label {{ font-size:12px; color:var(--text2); text-transform:uppercase; letter-spacing:.5px; }}
.stat-value {{ font-size:28px; font-weight:700; font-family:'JetBrains Mono',monospace; color:var(--accent); }}
.stat-sub {{ font-size:11px; color:var(--text2); margin-top:4px; }}

/* Highlight cards */
.highlight-row {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(180px,1fr)); gap:12px; margin-bottom:24px; }}
.hl-card {{ background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:16px; }}
.hl-card .hl-label {{ font-size:11px; color:var(--text2); text-transform:uppercase; }}
.hl-card .hl-value {{ font-size:22px; font-weight:600; font-family:'JetBrains Mono',monospace; margin-top:4px; }}
.hl-green {{ color:var(--green); }}
.hl-yellow {{ color:var(--yellow); }}
.hl-blue {{ color:var(--blue); }}
.hl-purple {{ color:var(--purple); }}

/* Tabs */
.tabs {{ display:flex; gap:6px; margin-bottom:16px; flex-wrap:wrap; }}
.tab-btn {{ background:var(--surface); border:1px solid var(--border); color:var(--text2); padding:8px 16px;
    border-radius:8px; cursor:pointer; font-size:13px; font-weight:500; transition:all .2s; font-family:'Inter',sans-serif; }}
.tab-btn:hover {{ border-color:var(--accent); color:var(--text); }}
.tab-btn.active {{ background:var(--accent); color:#000; border-color:var(--accent); font-weight:600; }}

/* Section */
.section-header {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; flex-wrap:wrap; gap:12px; }}
.section-header h2 {{ font-size:20px; }}
.section-stats {{ display:flex; gap:8px; flex-wrap:wrap; }}
.pill {{ padding:4px 12px; border-radius:20px; font-size:12px; font-weight:500; font-family:'JetBrains Mono',monospace; }}
.pill.green {{ background:var(--green-bg); color:var(--green); }}
.pill.yellow {{ background:var(--yellow-bg); color:var(--yellow); }}
.pill.blue {{ background:rgba(59,130,246,.12); color:var(--blue); }}
.pill.purple {{ background:rgba(139,92,246,.12); color:var(--purple); }}

/* Table */
.table-wrap {{ overflow-x:auto; border-radius:12px; border:1px solid var(--border); }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
thead {{ background:var(--surface2); position:sticky; top:0; }}
th {{ padding:10px 12px; text-align:left; font-weight:600; color:var(--text2); font-size:11px;
    text-transform:uppercase; letter-spacing:.5px; border-bottom:1px solid var(--border); }}
td {{ padding:8px 12px; border-bottom:1px solid var(--border); font-family:'JetBrains Mono',monospace; font-size:12px; }}
tr:hover {{ background:rgba(6,182,212,.04); }}
.row-approved {{ border-left:3px solid var(--green); }}
.row-conditional {{ border-left:3px solid var(--yellow); }}

.badge-approved {{ background:var(--green-bg); color:var(--green); padding:2px 8px; border-radius:4px; font-size:11px; font-weight:600; }}
.badge-conditional {{ background:var(--yellow-bg); color:var(--yellow); padding:2px 8px; border-radius:4px; font-size:11px; font-weight:600; }}
.dir-call {{ color:#10b981; font-weight:600; }}
.dir-put {{ color:#ef4444; font-weight:600; }}
.var-tag {{ background:rgba(139,92,246,.15); color:var(--purple); padding:1px 6px; border-radius:3px; font-size:11px; }}
.num {{ text-align:center; }}
.hit {{ color:var(--red); font-weight:600; }}
.ev-pos {{ color:var(--green); }}
.ev-neg {{ color:var(--red); }}
.p1a-good {{ color:var(--green); font-weight:600; }}
.p1a-warn {{ color:var(--yellow); }}

.wr-cell {{ position:relative; min-width:80px; }}
.wr-bar {{ position:absolute; left:0; top:0; bottom:0; background:rgba(16,185,129,.15); border-radius:3px; z-index:0; }}
.wr-cell span {{ position:relative; z-index:1; font-weight:600; }}

/* Search */
.search-box {{ margin-bottom:16px; }}
.search-box input {{ background:var(--surface); border:1px solid var(--border); color:var(--text); padding:10px 16px;
    border-radius:8px; width:100%; max-width:300px; font-family:'Inter',sans-serif; font-size:14px; }}
.search-box input:focus {{ outline:none; border-color:var(--accent); }}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>🔬 Oracle Quant — Grade Horária de Elite</h1>
        <div class="sub">Auto Quant Discovery v{info.get("versao","2.0")} — Catalogação {info.get("data_catalogacao","")}</div>
        <div class="meta">
            <span>📊 {info.get("total_ativos",9)} Ativos</span>
            <span>📈 {info.get("registros_carregados",0):,} Registros</span>
            <span>🔍 {info.get("hipoteses_geradas",0):,} Hipóteses</span>
            <span>⛏️ {info.get("padroes_minerados",0):,} Minerados</span>
            <span>⏱️ {info.get("duracao_segundos",0):.0f}s</span>
        </div>
    </div>

    <div class="highlight-row">
        <div class="hl-card"><div class="hl-label">Total Estratégias</div><div class="hl-value hl-blue">{len(grade):,}</div></div>
        <div class="hl-card"><div class="hl-label">✅ Aprovadas</div><div class="hl-value hl-green">{info.get("aprovadas",0):,}</div></div>
        <div class="hl-card"><div class="hl-label">⚠️ Condicionais</div><div class="hl-value hl-yellow">{info.get("condicionais",0):,}</div></div>
        <div class="hl-card"><div class="hl-label">❌ Reprovadas</div><div class="hl-value" style="color:var(--red)">{info.get("reprovadas",0):,}</div></div>
        <div class="hl-card"><div class="hl-label">📝 Escritas</div><div class="hl-value hl-purple">{info.get("estrategias_escritas",0):,}</div></div>
    </div>

    <h3 style="margin-bottom:12px;color:var(--text2);font-size:13px;text-transform:uppercase;letter-spacing:1px;">Estratégias por Ativo</h3>
    <div class="stats-grid">{ativo_cards}</div>

    <div class="search-box"><input type="text" placeholder="🔍 Buscar horário (ex: 14:30)" onkeyup="filterRows(this.value)"></div>

    <div class="tabs">
        <button class="tab-btn active" onclick="showAtivo('ALL')" id="tab-ALL">Todos</button>
        {ativo_tabs}
    </div>

    {ativo_sections}
</div>

<script>
const allSections = document.querySelectorAll('.ativo-section');
const allTabs = document.querySelectorAll('.tab-btn');

function showAtivo(id) {{
    allTabs.forEach(t => t.classList.remove('active'));
    document.getElementById('tab-' + id).classList.add('active');
    allSections.forEach(s => {{
        s.style.display = (id === 'ALL' || s.id === 'sec-' + id) ? 'block' : 'none';
    }});
}}

function filterRows(query) {{
    document.querySelectorAll('tbody tr').forEach(row => {{
        const hora = row.children[0]?.textContent || '';
        row.style.display = hora.includes(query) ? '' : 'none';
    }});
}}

// Show all by default
showAtivo('ALL');
</script>
</body>
</html>'''

    out_path = Path(json_path).with_suffix(".html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ HTML gerado: {out_path}")
    print(f"   Abra no navegador para visualizar!")
    return str(out_path)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        # Tenta achar o mais recente na pasta catalogacao
        pasta = Path("catalogacao")
        jsons = sorted(pasta.glob("grade_horaria_*.json"))
        if jsons:
            path = str(jsons[-1])
        else:
            print("Uso: python preview_catalogacao.py <arquivo.json>")
            sys.exit(1)
    else:
        path = sys.argv[1]
    gerar_html(path)
