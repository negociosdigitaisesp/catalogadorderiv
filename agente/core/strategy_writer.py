"""
agente/core/strategy_writer.py
=====================================
Auto Quant Discovery — Fase 4 — O Arquiteto da Grade Horária

Responsabilidade:
  Recebe oportunidades APROVADAS/CONDICIONAIS pelo StrategyValidator e:
  1. Gera ID temporal: T{HHMM}_{DIA}_{ATIVO}_G2 (ex: T1430_SEG_R75_G2)
  2. Atualiza o config.json com o novo schema de AGENDA de horários
  3. Notifica Supabase (public.hft_oracle_results) com os campos de horário
  4. Gera relatório de Grade com tabela de recuperação Gale 2

NOVO SCHEMA config.json (por estratégia):
  {
    "strategy_id":  "T1430_SEG_R75_G2",
    "ativo":        "R_75",
    "hh_mm":        "14:30",
    "dia_semana":   1,
    "direcao":      "CALL",
    "win_rate_g2":  0.96,
    "score_30_7":   0.93,
    "max_gale":     2,
    "status":       "APROVADO",
    "stake":        1.0,
    "win_1a_rate":  0.62,
    "win_gale1_rate": 0.27,
    "win_gale2_rate": 0.07,
    "hit_rate":     0.04,
    "ev_gale2":     0.55,
    "descoberta_em": 1772119689,
    "valid_until":  1779895689
  }

REGRAS ABSOLUTAS (PRD):
  - Sem datetime.now() para lógica de trading
  - Limpa entradas Z-Score antigas (estrategias sem hh_mm)
  - async/await no notify_supabase
  - Tipagem forte
"""

from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path
from time import time
from typing import Any

logger = logging.getLogger(__name__)

# ─── Constantes ───────────────────────────────────────────────────────────────
_CONFIG_SECTION     = "grade_horaria"       # chave no config.json
_SUPABASE_TABLE     = "hft_oracle_results"  # tabela pública Supabase
_90_DIAS_SEGUNDOS   = 90 * 24 * 3600

# Mapa de dia_semana (int) → sigla 3 letras
_DIA_SIGLA = {
    0: "SEG", 1: "TER", 2: "QUA", 3: "QUI",
    4: "SEX", 5: "SAB", 6: "DOM",
}


class StrategyWriter:
    """
    Arquiteto da Grade Horária de Elite.

    Transforma resultados validados pelo StrategyValidator na agenda de entrada
    do VPS Sniper: config.json atualizado + Supabase notificado.

    Uso:
        writer = StrategyWriter()
        await writer.write_all(validated_batch, supabase_client)
    """

    # ─────────────────────────────────────────────────────────────────────────
    # MÉTODO 1: generate_strategy_id  (ID Temporal)
    # ─────────────────────────────────────────────────────────────────────────

    def generate_strategy_id(
        self,
        ativo: str,
        contexto: dict,
        config_path: str = "config.json",
    ) -> str:
        """
        Gera ID temporal único: T{HHMM}_{DIA}_{ATIVO}_G2

        Exemplos:
          hh_mm='14:30', dia_semana=0, ativo='R_75' → 'T1430_SEG_R75_G2'
          hh_mm='09:05', dia_semana=4, ativo='BOOM500' → 'T0905_SEX_BOOM500_G2'
        """
        hh_mm      = str(contexto.get("hh_mm", "0000")).replace(":", "")
        dia_int    = int(contexto.get("dia_semana", 0))
        dia_sigla  = _DIA_SIGLA.get(dia_int, f"D{dia_int}")
        ativo_safe = ativo.replace("_", "").replace("-", "").upper()

        return f"T{hh_mm}_{dia_sigla}_{ativo_safe}_G2"

    # ─────────────────────────────────────────────────────────────────────────
    # MÉTODO 2: build_config_entry
    # ─────────────────────────────────────────────────────────────────────────

    def build_config_entry(
        self,
        validated_result: dict,
        config_path: str = "config.json",
    ) -> dict:
        """
        Constrói a entrada do config.json para o novo schema de Grade Horária.

        Extrai todos os campos do resultado do StrategyValidator v2.
        """
        mined   = validated_result["mined_result"]
        hyp     = mined["hypothesis"]
        status  = validated_result["status"]
        contexto = hyp.get("contexto", {})

        ativo           = hyp.get("ativo", "UNKNOWN")
        hh_mm           = contexto.get("hh_mm", "00:00")
        dia_semana      = int(contexto.get("dia_semana", 0))
        direcao         = hyp.get("direcao", "CALL")
        mhi_seq         = contexto.get("mhi_seq")          # pode ser None (V1/V4)

        win_rate_g2     = float(mined.get("win_rate_final",  0.0))
        score_30_7      = float(mined.get("score_ponderado", win_rate_g2))
        ev_gale2        = float(mined.get("ev_final",        0.0))
        win_1a_rate     = float(validated_result.get("win_1a_rate",    0.0))
        win_gale1_rate  = float(validated_result.get("win_gale1_rate", 0.0))
        win_gale2_rate  = float(validated_result.get("win_gale2_rate", 0.0))
        hit_rate        = float(validated_result.get("hit_rate",       0.0))
        stake           = float(validated_result.get("stake_multiplier", 0.5))
        variacao        = mined.get("variacao", "V1")
        # Quantidades reais (transparencia total para auditoria)
        n_total         = int(mined.get("n_total",    mined.get("n_test", 0)))
        n_win_1a        = int(mined.get("n_win_1a",   0))
        n_win_g1        = int(mined.get("n_win_g1",   0))
        n_win_g2        = int(mined.get("n_win_g2",   0))
        n_hit_count     = int(mined.get("n_hit",      0))
        kelly_quarter   = float(validated_result.get("kelly_quarter", stake / 4.0))

        strategy_id = self.generate_strategy_id(ativo, contexto, config_path)

        descoberta_em = int(time())
        valid_until   = descoberta_em + _90_DIAS_SEGUNDOS

        entry: dict[str, Any] = {
            "strategy_id":    strategy_id,
            "ativo":          ativo,
            "hh_mm":          hh_mm,
            "dia_semana":     dia_semana,
            "dia_nome":       _DIA_SIGLA.get(dia_semana, f"D{dia_semana}"),
            "direcao":        direcao,
            "win_rate_g2":    round(win_rate_g2,    6),
            "score_30_7":     round(score_30_7,     6),
            "ev_gale2":       round(ev_gale2,       6),
            "max_gale":       2,   # fixo conforme PRD
            "status":         status,
            "stake":          stake,
            "kelly_quarter":  round(kelly_quarter,  6),
            "win_1a_rate":    round(win_1a_rate,    6),
            "win_gale1_rate": round(win_gale1_rate, 6),
            "win_gale2_rate": round(win_gale2_rate, 6),
            "hit_rate":       round(hit_rate,       6),
            # Quantidades reais (transparencia total)
            "n_total":        n_total,
            "n_win_1a":       n_win_1a,
            "n_win_g1":       n_win_g1,
            "n_win_g2":       n_win_g2,
            "n_hit":          n_hit_count,
            "variacao":       variacao,
            "descoberta_em":  descoberta_em,
            "valid_until":    valid_until,
        }

        # Adiciona mhi_seq apenas para V2 (quando não é None)
        if mhi_seq:
            entry["mhi_seq"] = mhi_seq

        return entry

    # ─────────────────────────────────────────────────────────────────────────
    # MÉTODO 3: update_config_json
    # ─────────────────────────────────────────────────────────────────────────

    def update_config_json(
        self,
        new_entry: dict,
        config_path: str = "config.json",
    ) -> None:
        """
        Atualiza a seção 'grade_horaria' do config.json.

        LIMPEZA AUTOMÁTICA: remove entradas Z-Score antigas
        (entradas que não possuem 'hh_mm').
        """
        path = Path(config_path)
        config: dict = {}

        if path.exists() and path.stat().st_size > 0:
            try:
                with open(path, encoding="utf-8") as fp:
                    config = json.load(fp)
            except json.JSONDecodeError:
                config = {}

        # Garante seção grade_horaria
        grade: list[dict] = config.get(_CONFIG_SECTION, [])

        # ── Limpa estratégias Z-Score antigas (sem hh_mm) ────────────────────
        antes = len(grade)
        grade = [e for e in grade if "hh_mm" in e]
        if len(grade) < antes:
            logger.info(
                "[WRITER] Limpeza: %d entradas Z-Score removidas do config.json",
                antes - len(grade),
            )

        # ── Upsert por strategy_id ────────────────────────────────────────────
        strategy_id = new_entry["strategy_id"]
        for i, entry in enumerate(grade):
            if entry.get("strategy_id") == strategy_id:
                grade[i] = new_entry
                logger.info("[WRITER] Estrategia %s atualizada no config.json", strategy_id)
                break
        else:
            grade.append(new_entry)
            logger.info("[WRITER] Estrategia %s adicionada ao config.json", strategy_id)

        # Ordena por hora de entrada para facilitar leitura do Sniper
        grade.sort(key=lambda e: (e.get("dia_semana", 0), e.get("hh_mm", "00:00")))

        config[_CONFIG_SECTION] = grade

        # Remove seção legada "estrategias" (Z-Score)
        if "estrategias" in config:
            del config["estrategias"]
            logger.info("[WRITER] Secao 'estrategias' (Z-Score) removida do config.json")

        with open(path, "w", encoding="utf-8") as fp:
            json.dump(config, fp, ensure_ascii=False, indent=2)

    # ─────────────────────────────────────────────────────────────────────────
    # MÉTODO 4: notify_supabase
    # ─────────────────────────────────────────────────────────────────────────

    async def notify_supabase(
        self,
        new_entry: dict,
        supabase_client: Any,
    ) -> None:
        """
        Faz upsert na tabela hft_oracle_results com colunas planas de auditoria.

        Campos explícitos (consultáveis por ativo sem parsing JSON):
          - variacao_estrategia: V1, V2, V3, V4...
          - n_win_1a, n_win_g1, n_win_g2, n_hit, n_total
          - win_rate, ev_real, status, sizing_override

        config_otimizada (JSONB) reduzido a campos essenciais do Sniper.
        """
        payload = {
            # Identificação
            "ativo":                new_entry["ativo"],
            "estrategia":           f"GRADE_G2_{new_entry['hh_mm'].replace(':','')}_{new_entry['dia_nome']}",
            "strategy_id":          new_entry["strategy_id"],
            # Métricas de performance
            "win_rate":             new_entry["win_rate_g2"],
            "n_amostral":           new_entry["n_total"],
            "ev_real":              new_entry["ev_gale2"],
            "edge_vs_be":           round(new_entry["win_rate_g2"] - (1.0 / 1.85), 6),
            "status":               new_entry["status"],
            "sizing_override":      new_entry["stake"],
            # ── Colunas de auditoria (migração 005) ──────────────────────
            "variacao_estrategia":  new_entry["variacao"],
            "n_win_1a":             new_entry["n_win_1a"],
            "n_win_g1":             new_entry["n_win_g1"],
            "n_win_g2":             new_entry["n_win_g2"],
            "n_hit":                new_entry["n_hit"],
            "n_total":              new_entry["n_total"],
            # ── JSONB simplificado (só o essencial para o Sniper) ────────
            "config_otimizada": {
                "tipo":           "HORARIO",
                "hh_mm":          new_entry["hh_mm"],
                "dia_semana":     new_entry["dia_semana"],
                "direcao":        new_entry["direcao"],
                "max_gale":       new_entry["max_gale"],
                "variacao":       new_entry["variacao"],
                "win_1a_rate":    new_entry["win_1a_rate"],
                "win_gale1_rate": new_entry["win_gale1_rate"],
                "win_gale2_rate": new_entry["win_gale2_rate"],
                "hit_rate":       new_entry["hit_rate"],
            },
            "last_update": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        try:
            supabase_client.table(_SUPABASE_TABLE).upsert(
                payload,
                on_conflict="ativo,estrategia,strategy_id",
            ).execute()
            logger.info(
                "[WRITER] Supabase notificado: %s @ %s %s (%s)",
                new_entry["ativo"],
                new_entry["hh_mm"],
                new_entry["dia_nome"],
                new_entry["variacao"],
            )
        except Exception as exc:
            logger.error(
                "[WRITER] Erro Supabase para %s: %s",
                new_entry["strategy_id"], exc,
            )
            raise

    # ─────────────────────────────────────────────────────────────────────────
    # MÉTODO 5: write_strategy_report
    # ─────────────────────────────────────────────────────────────────────────

    def write_strategy_report(
        self,
        validated_result: dict,
        output_path: str = "catalog/reports/",
        new_entry: dict | None = None,
    ) -> str:
        """
        Gera relatório de Grade com Tabela de Recuperação Gale 2.
        Destaca horários com Win Rate >= 95% como 'Alta Recorrência'.
        """
        if new_entry is None:
            new_entry = self.build_config_entry(validated_result)

        strategy_id  = new_entry["strategy_id"]
        ativo        = new_entry["ativo"]
        hh_mm        = new_entry["hh_mm"]
        dia_nome     = new_entry["dia_nome"]
        direcao      = new_entry["direcao"]
        status       = new_entry["status"]
        win_rate_g2  = new_entry["win_rate_g2"]
        score_30_7   = new_entry["score_30_7"]
        ev_gale2     = new_entry["ev_gale2"]
        stake        = new_entry["stake"]
        variacao     = new_entry["variacao"]
        win_1a       = new_entry["win_1a_rate"]
        win_g1       = new_entry["win_gale1_rate"]
        win_g2       = new_entry["win_gale2_rate"]
        hit          = new_entry["hit_rate"]

        # Rótulo de destaque
        recorrencia_label = (
            "*** HORARIO DE ALTA RECORRENCIA (95%+) ***"
            if win_rate_g2 >= 0.95
            else "Horario Condicional (90-95%)"
        )

        motivo = validated_result.get("motivo", "-")
        descoberta_str = _epoch_to_readable(new_entry["descoberta_em"])
        validade_str   = _epoch_to_readable(new_entry["valid_until"])

        report = f"""
===========================================================
 GRADE HORARIA DE ELITE — NOVA ENTRADA
===========================================================
 ID:         {strategy_id}
 Ativo:      {ativo}
 Horario:    {hh_mm} UTC  |  {dia_nome}
 Direcao:    {direcao}
 Variacao:   {variacao}
 Status:     {status}
 {recorrencia_label}
===========================================================
 TABELA DE RECUPERACAO GALE 2
===========================================================
 Win de 1a:    {win_1a:.1%}  (entrada direta)
 Win Gale 1:   {win_g1:.1%}  (recupera entrada perdida)
 Win Gale 2:   {win_g2:.1%}  (recupera Gale 1 perdido)
 Hit Total:    {hit:.1%}   (perda do ciclo completo)
-----------------------------------------------------------
 Win Rate G2:  {win_rate_g2:.2%}  (Gale 1 + Gale 2 + 1a)
 EV Gale 2:   {ev_gale2:+.4f} unidades/ciclo
 Score 30/7:   {score_30_7:.4f}
===========================================================
 SIZING
===========================================================
 Stake Base:   {stake}x
 Max Gale:     2 entradas complementares
 Stakes:       1.0 -> 2.2 -> 5.0 (total: 8.2 se hit)
===========================================================
 DIAGNOSTICO
===========================================================
 {motivo}
===========================================================
 Descoberta:  {descoberta_str}
 Valida ate:  {validade_str}
===========================================================
"""
        out_dir  = Path(output_path)
        out_dir.mkdir(parents=True, exist_ok=True)
        filepath = out_dir / f"report_{strategy_id}.txt"

        with open(filepath, "w", encoding="utf-8") as fp:
            fp.write(report)

        logger.info("[WRITER] Relatorio gerado: %s", filepath)
        return str(filepath)

    # ─────────────────────────────────────────────────────────────────────────
    # MÉTODO 6: write_all  (async — orquestrador)
    # ─────────────────────────────────────────────────────────────────────────

    async def write_all(
        self,
        validated_batch: dict,
        supabase_client: Any,
        config_path: str = "config.json",
        report_path: str = "catalog/reports/",
    ) -> dict:
        """
        Processa batch completo: APROVADO + CONDICIONAL.
        Para cada um: build_config_entry → update_config_json →
        notify_supabase → write_strategy_report.
        """
        aprovadas_list    = validated_batch.get("aprovados",    [])
        condicionais_list = validated_batch.get("condicionais", [])
        todas             = aprovadas_list + condicionais_list

        n_aprovadas    = 0
        n_condicionais = 0
        reports: list[str] = []
        config_ok   = False
        supabase_ok = False

        for validated in todas:
            status = validated.get("status", "REPROVADO")
            if status not in ("APROVADO", "CONDICIONAL"):
                continue

            ativo       = validated["mined_result"]["hypothesis"].get("ativo", "?")
            strategy_id = "(calculando)"

            try:
                new_entry   = self.build_config_entry(validated, config_path)
                strategy_id = new_entry["strategy_id"]

                logger.info(
                    "[WRITER] Processando %s @ %s %s (%s)",
                    ativo,
                    new_entry["hh_mm"],
                    new_entry["dia_nome"],
                    status,
                )

                # 1. Salva no config.json
                self.update_config_json(new_entry, config_path)
                config_ok = True

                # 2. Notifica Supabase (async)
                await self.notify_supabase(new_entry, supabase_client)
                supabase_ok = True

                # 3. Gera relatório
                report_file = self.write_strategy_report(
                    validated, report_path, new_entry=new_entry
                )
                reports.append(report_file)

                if status == "APROVADO":
                    n_aprovadas += 1
                else:
                    n_condicionais += 1

            except Exception as exc:
                logger.error(
                    "[WRITER] Erro ao escrever %s (%s): %s",
                    strategy_id, ativo, exc,
                )
                continue

        total = n_aprovadas + n_condicionais
        logger.info(
            "[WRITER] Ciclo concluido: %d escritas (%d aprovadas | %d condicionais)",
            total, n_aprovadas, n_condicionais,
        )

        return {
            "estrategias_escritas": total,
            "aprovadas":            n_aprovadas,
            "condicionais":         n_condicionais,
            "config_atualizado":    config_ok,
            "supabase_notificado":  supabase_ok,
            "reports_gerados":      reports,
        }


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _epoch_to_readable(epoch: int) -> str:
    """Converte epoch para string ISO legível (apenas para relatórios)."""
    try:
        dt = datetime.datetime.fromtimestamp(epoch, datetime.UTC)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return str(epoch)
