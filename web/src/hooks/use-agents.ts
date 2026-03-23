import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { AgentSummary } from "@/lib/types";

export function useAgents() {
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    apiFetch<AgentSummary[]>("/api/agents")
      .then((data) => {
        if (!cancelled) {
          setAgents(data);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to fetch agents");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  return { agents, loading, error };
}
