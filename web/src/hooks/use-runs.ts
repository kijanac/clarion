import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { AgentRun } from "@/lib/types";

export function useRuns(agentId: string | null) {
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!agentId) {
      setRuns([]);
      setLoading(false);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    apiFetch<AgentRun[]>(`/api/agents/${agentId}/runs`)
      .then((data) => {
        if (!cancelled) {
          setRuns(data);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to fetch runs");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [agentId]);

  return { runs, loading, error };
}
