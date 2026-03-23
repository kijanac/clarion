import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { AgentDetail } from "@/lib/types";

export function useAgent(agentId: string | null) {
  const [agent, setAgent] = useState<AgentDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!agentId) {
      setAgent(null);
      setLoading(false);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    apiFetch<AgentDetail>(`/api/agents/${agentId}`)
      .then((data) => {
        if (!cancelled) {
          setAgent(data);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to fetch agent");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [agentId]);

  return { agent, loading, error };
}
