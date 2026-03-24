import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { TemplateDetail } from "@/lib/types";

export function useTemplate(templateId: string | null) {
  const [template, setTemplate] = useState<TemplateDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const refetch = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (!templateId) {
      setTemplate(null);
      setLoading(false);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    apiFetch<TemplateDetail>(`/api/templates/${templateId}`)
      .then((data) => {
        if (!cancelled) {
          setTemplate(data);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Couldn't load template");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [templateId, tick]);

  return { template, loading, error, refetch };
}
