/**
 * useHftExecutionBridge.ts
 * ─────────────────────────────────────────────────────────────────────────────
 * Hook de ponte entre o Supabase Realtime e o Dashboard HFT.
 *
 * REGRA DO MINUTO SOBERANO:
 *   Para cada slot HH:MM, apenas o PRIMEIRO sinal PRE_SIGNAL recebido é
 *   aceito. Qualquer sinal subsequente para o mesmo minuto é bloqueado com
 *   log de aviso — garantindo que o painel nunca mostre 2+ operações abertas
 *   simultaneamente para o mesmo horário.
 *
 * Uso:
 *   const { signals, pendingMinutes, lastSignal } = useHftExecutionBridge();
 */

import { useEffect, useState, useCallback, useRef } from 'react';
import { supabase } from '../lib/supabaseClient';

// ─── Tipos ───────────────────────────────────────────────────────────────────

export interface HftSignal {
  id:                number;
  ativo:             string;
  estrategia:        string;
  direcao:           'CALL' | 'PUT';
  p_win_historica:   number;
  status:            'PRE_SIGNAL' | 'CONFIRMED' | 'EXPIRED';
  timestamp_sinal:   number;
  contexto:          {
    execution?: { hh_mm_target?: string; [key: string]: unknown };
    metrics?:   { win_rate_g2?: number; ev_gale2?: number; sizing?: number; [key: string]: unknown };
    [key: string]: unknown;
  };
  created_at?:       string;
}

// ─── Constante: janela de soberania (ms) ─────────────────────────────────────
// Quanto tempo um slot HH:MM permanece "ocupado" após receber um PRE_SIGNAL.
// 70s cobre o ciclo completo (PRE_SIGNAL :50 → CONFIRMED :00 → margem).
const SOVEREIGN_WINDOW_MS = 70_000;

// ─────────────────────────────────────────────────────────────────────────────

export function useHftExecutionBridge(tableName = 'hft_catalogo_estrategias') {
  const [signals, setSignals]           = useState<HftSignal[]>([]);
  const [loading, setLoading]           = useState(true);
  const [error, setError]               = useState<string | null>(null);

  // Set de slots "ocupados": chave = "HH:MM", valor = timestamp de quando expira
  const pendingMinutesRef = useRef<Map<string, number>>(new Map());
  const [pendingMinutes, setPendingMinutes] = useState<Set<string>>(new Set());

  // ── Helpers ────────────────────────────────────────────────────────────────

  const extractHhMm = (signal: HftSignal): string | null =>
    signal.contexto?.execution?.hh_mm_target ?? null;

  /**
   * Verifica se o slot HH:MM já está ocupado pela trava soberana.
   * Expira travamentos antigos automaticamente.
   */
  const isSovereignBlocked = useCallback((hh_mm: string): boolean => {
    const expiresAt = pendingMinutesRef.current.get(hh_mm);
    if (expiresAt === undefined) return false;
    if (Date.now() > expiresAt) {
      pendingMinutesRef.current.delete(hh_mm);
      setPendingMinutes(new Set(pendingMinutesRef.current.keys()));
      return false;
    }
    return true;
  }, []);

  /**
   * Registra o slot HH:MM como ocupado por SOVEREIGN_WINDOW_MS ms.
   */
  const lockSovereignSlot = useCallback((hh_mm: string, ativo: string) => {
    pendingMinutesRef.current.set(hh_mm, Date.now() + SOVEREIGN_WINDOW_MS);
    setPendingMinutes(new Set(pendingMinutesRef.current.keys()));
    console.log(`[SOVEREIGN] Slot ${hh_mm} bloqueado para ${ativo} por ${SOVEREIGN_WINDOW_MS / 1000}s`);
  }, []);

  // ── Processador de sinal recebido ──────────────────────────────────────────

  const processIncoming = useCallback((signal: HftSignal) => {
    const hh_mm = extractHhMm(signal);

    if (signal.status === 'PRE_SIGNAL' && hh_mm) {
      if (isSovereignBlocked(hh_mm)) {
        console.log(
          `[SOVEREIGN] Sinal para ${signal.ativo} ignorado. ` +
          `Já existe uma operação pendente para este minuto (${hh_mm}).`
        );
        return; // Bloqueia — não adiciona ao estado
      }
      lockSovereignSlot(hh_mm, signal.ativo);
    }

    setSignals((prev) => {
      // Evita duplicatas por id
      if (prev.some((s) => s.id === signal.id)) return prev;
      return [signal, ...prev].slice(0, 50); // ring-buffer de 50 sinais
    });
  }, [isSovereignBlocked, lockSovereignSlot]);

  // ── Carregamento inicial ───────────────────────────────────────────────────

  const fetchRecent = useCallback(async () => {
    try {
      const { data, error: fetchErr } = await supabase
        .from(tableName)
        .select('*')
        .in('status', ['PRE_SIGNAL', 'CONFIRMED'])
        .order('timestamp_sinal', { ascending: false })
        .limit(20);

      if (fetchErr) throw fetchErr;
      setSignals(data as HftSignal[] || []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [tableName]);

  // ── Subscrição Realtime ────────────────────────────────────────────────────

  useEffect(() => {
    fetchRecent();

    const channel = supabase
      .channel(`hft_execution_bridge_${tableName}`)
      .on(
        'postgres_changes',
        { event: 'INSERT', schema: 'public', table: tableName },
        (payload) => {
          const signal = payload.new as HftSignal;
          processIncoming(signal);
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [fetchRecent, processIncoming, tableName]);

  // ── API pública ────────────────────────────────────────────────────────────

  const preSignals  = signals.filter((s) => s.status === 'PRE_SIGNAL');
  const confirmed   = signals.filter((s) => s.status === 'CONFIRMED');
  const lastSignal  = signals.length > 0 ? signals[0] : null;

  return {
    signals,
    preSignals,
    confirmed,
    lastSignal,
    pendingMinutes,   // Set<string> de slots HH:MM atualmente bloqueados
    loading,
    error,
  };
}
