import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { RunDetail } from "@/lib/types";

export function useRunDetail(agentId: string | null, runId: string | null) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!agentId || !runId) {
      setRun(null);
      setLoading(false);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    apiFetch<RunDetail>(`/api/agents/${agentId}/runs/${runId}`)
      .then((data) => {
        if (!cancelled) {
          setRun(data);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Couldn't load run details");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [agentId, runId]);

  return { run, loading, error };
}
