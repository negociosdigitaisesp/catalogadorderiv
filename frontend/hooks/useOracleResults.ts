import { useEffect, useState, useCallback } from 'react';
import { supabase } from '../lib/supabaseClient';
import { OracleResult } from '../types/discovery';

export function useOracleResults() {
  const [strategies, setStrategies] = useState<OracleResult[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchInitialData = useCallback(async () => {
    try {
      const { data, error } = await supabase
        .from('hft_oracle_results')
        .select('*')
        .order('last_update', { ascending: false });

      if (error) throw error;
      setStrategies(data || []);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchInitialData();

    const channel = supabase
      .channel('oracle_results_changes')
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'hft_oracle_results' },
        (payload) => {
          setStrategies((prev) => {
            if (payload.eventType === 'INSERT') {
              const newStrat = { ...payload.new, _isNew: true } as OracleResult & { _isNew?: boolean };
              // Remove the _isNew flag after 30 seconds to stop pulsing
              setTimeout(() => {
                setStrategies((currentList) =>
                  currentList.map((s) => (s.id === newStrat.id ? { ...s, _isNew: false } : s))
                );
              }, 30000);
              return [newStrat, ...prev];
            }
            if (payload.eventType === 'UPDATE') {
              return prev.map((s) => (s.id === payload.new.id ? (payload.new as OracleResult) : s));
            }
            if (payload.eventType === 'DELETE') {
              return prev.filter((s) => s.id !== payload.old.id);
            }
            return prev;
          });
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [fetchInitialData]);

  const approved = strategies.filter((s) => s.status === 'APROVADO');
  const conditional = strategies.filter((s) => s.status === 'CONDICIONAL');

  return { strategies, loading, error, approved, conditional };
}
