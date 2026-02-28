"""
Script de smoke test para o StrategyValidator v2.
"""
import sys, logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
sys.path.insert(0, '.')
from agente.core.strategy_validator import StrategyValidator

validator = StrategyValidator()

aprovado_mock = {
    'win_rate_final':  0.96,
    'ev_final':        0.55,
    'n_test':          25,
    'score_ponderado': 0.93,
    'p_1a':   0.62,
    'p_gale1': 0.27,
    'p_gale2': 0.07,
    'p_hit':   0.04,
    'hypothesis': {'ativo': 'BOOM300N', 'contexto': {'hh_mm': '13:55', 'dia_semana': 0}, 'direcao': 'CALL'},
}

condicional_mock = {
    'win_rate_final':  0.91,
    'ev_final':        0.20,
    'n_test':          12,
    'score_ponderado': 0.88,
    'p_1a':   0.55,
    'p_gale1': 0.28,
    'p_gale2': 0.08,
    'p_hit':   0.09,
    'hypothesis': {'ativo': 'CRASH500', 'contexto': {'hh_mm': '09:30', 'dia_semana': 2}, 'direcao': 'PUT'},
}

reprovado_mock = {
    'win_rate_final':  0.84,
    'ev_final':        -0.30,
    'n_test':          30,
    'score_ponderado': 0.82,
    'p_1a':   0.50,
    'p_gale1': 0.25,
    'p_gale2': 0.09,
    'p_hit':   0.16,
    'hypothesis': {'ativo': 'R_100', 'contexto': {'hh_mm': '22:00', 'dia_semana': 5}, 'direcao': 'CALL'},
}

batch = validator.validate_batch([aprovado_mock, condicional_mock, reprovado_mock])

print()
print("=== RESULTADO DO BATCH ===")
print(f"Aprovados:    {len(batch['aprovados'])}")
print(f"Condicionais: {len(batch['condicionais'])}")
print(f"Reprovados:   {len(batch['reprovados'])}")

for status_key in ['aprovados', 'condicionais', 'reprovados']:
    for r in batch[status_key]:
        ativo = r['mined_result']['hypothesis']['ativo']
        hhmm  = r['mined_result']['hypothesis']['contexto'].get('hh_mm')
        print()
        print(f"  [{r['status']}] {ativo} @ {hhmm}")
        print(f"  Motivo:  {r['motivo']}")
        print(f"  Taxas:   1a={r['win_1a_rate']:.1%} | G1={r['win_gale1_rate']:.1%} | G2={r['win_gale2_rate']:.1%} | Hit={r['hit_rate']:.1%}")
        print(f"  Stake:   {r['stake_multiplier']}x | EV Gale2: {r['ev_gale2']}")
