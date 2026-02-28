export interface OracleResult {
  id: number;
  ativo: string;
  estrategia: string;
  strategy_id: string;
  win_rate: number;
  n_amostral: number;
  ev_real: number;
  edge_vs_be: number;
  sharpe: number;
  p_value: number;
  status: "APROVADO" | "CONDICIONAL" | "REPROVADO";
  config_otimizada: Record<string, unknown>;
  sizing_override: number;
  valid_until: number;
  last_update: number;
  sniper_active: boolean;
}

export interface AgentCycle {
  id: number;
  started_at: number;
  duration_seconds: number;
  registros_carregados: number;
  hipoteses_geradas: number;
  padroes_minerados: number;
  aprovadas: number;
  condicionais: number;
  reprovadas: number;
  estrategias_escritas: number;
}
