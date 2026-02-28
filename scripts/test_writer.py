"""
Smoke test para StrategyWriter v2 — Grade Horaria
"""
import sys, asyncio, json, os
sys.path.insert(0, '.')
from agente.core.strategy_writer import StrategyWriter

writer = StrategyWriter()

# Simula resultado APROVADO do StrategyValidator v2
validated_aprovado = {
    'status':       'APROVADO',
    'motivo':       'Aprovado por recorrencia alta (WR=96.0%, N=25, score=0.93)',
    'stake_multiplier': 1.0,
    'win_1a_rate':    0.62,
    'win_gale1_rate': 0.27,
    'win_gale2_rate': 0.07,
    'hit_rate':       0.04,
    'ev_gale2':       0.55,
    'kelly_quarter':  0.25,
    'sharpe':         0.0,
    'p_value':        0.96,
    'criterios_aprovados': 3,
    'mined_result': {
        'win_rate_final':  0.96,
        'ev_final':        0.55,
        'n_test':          25,
        'score_ponderado': 0.93,
        'p_1a':            0.62,
        'p_gale1':         0.27,
        'p_gale2':         0.07,
        'p_hit':           0.04,
        'variacao':        'V4',
        'horario_alvo':    '14:30',
        'hypothesis': {
            'ativo':    'R_75',
            'direcao':  'CALL',
            'contexto': {
                'hh_mm':      '14:30',
                'dia_semana': 1,
            },
        },
    },
}

# Simula resultado CONDICIONAL
validated_condicional = {
    'status':       'CONDICIONAL',
    'motivo':       'Condicional (WR=91.0%, N=12, score=0.88)',
    'stake_multiplier': 0.5,
    'win_1a_rate':    0.55,
    'win_gale1_rate': 0.28,
    'win_gale2_rate': 0.08,
    'hit_rate':       0.09,
    'ev_gale2':       0.20,
    'kelly_quarter':  0.125,
    'sharpe':         0.0,
    'p_value':        0.91,
    'criterios_aprovados': 2,
    'mined_result': {
        'win_rate_final':  0.91,
        'ev_final':        0.20,
        'n_test':          12,
        'score_ponderado': 0.88,
        'p_1a':            0.55,
        'p_gale1':         0.28,
        'p_gale2':         0.08,
        'p_hit':           0.09,
        'variacao':        'V2',
        'horario_alvo':    '09:30',
        'hypothesis': {
            'ativo':    'BOOM300N',
            'direcao':  'PUT',
            'contexto': {
                'hh_mm':      '09:30',
                'dia_semana': 4,
                'mhi_seq':    'V-R-V',
            },
        },
    },
}

# Testa build_config_entry
entry1 = writer.build_config_entry(validated_aprovado)
entry2 = writer.build_config_entry(validated_condicional)

print("=== ENTRIES GERADAS ===")
print(json.dumps(entry1, indent=2, ensure_ascii=False))
print()
print(json.dumps(entry2, indent=2, ensure_ascii=False))

# Testa update_config_json (usa config_test.json para nao sujar o real)
test_config = 'catalog/test_config.json'
import pathlib
pathlib.Path('catalog').mkdir(exist_ok=True)

# Cria config antigo com estrategia Z-Score para testar limpeza
with open(test_config, 'w') as f:
    json.dump({'estrategias': [{'strategy_id': 'S1_OLD', 'p_win': 0.55}]}, f)

writer.update_config_json(entry1, test_config)
writer.update_config_json(entry2, test_config)

with open(test_config) as f:
    result = json.load(f)

print()
print("=== CONFIG.JSON RESULTANTE ===")
print(json.dumps(result, indent=2, ensure_ascii=False))

# Testa geracao de relatorio
report_file = writer.write_strategy_report(validated_aprovado, 'catalog/reports/', entry1)
print()
print(f"Relatorio gerado: {report_file}")
with open(report_file) as f:
    print(f.read())

# Limpeza
os.remove(test_config)
print("OK - Smoke test concluido!")
