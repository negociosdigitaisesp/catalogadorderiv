import { useEffect, useState, useCallback } from 'react';
import { supabase } from '../lib/supabaseClient';
import { AgentCycle } from '../types/discovery';

export function useAgentCycles() {
  const [cycles, setCycles] = useState<AgentCycle[]>([]);
  const [loading, setLoading] = useState<boolean>(true);

  const fetchInitialData = useCallback(async () => {
    try {
      const { data, error } = await supabase
        .from('agent_cycles')
        .select('*')
        .order('started_at', { ascending: false })
        .limit(10);

      if (error) throw error;
      setCycles(data || []);
    } catch (err: any) {
      console.error('Error loading agent cycles:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchInitialData();

    const channel = supabase
      .channel('agent_cycles_changes')
      .on(
        'postgres_changes',
        { event: 'INSERT', schema: 'public', table: 'agent_cycles' },
        (payload) => {
          setCycles((prev) => {
            const newCycle = payload.new as AgentCycle;
            const updated = [newCycle, ...prev].slice(0, 10);
            return updated;
          });
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [fetchInitialData]);

  const lastCycleAt = cycles.length > 0 ? cycles[0].started_at : null;

  return { cycles, loading, lastCycleAt };
}
