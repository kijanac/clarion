import type { AgentSummary } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { StatusDot } from "@/components/status-dot";
import { relativeTime, formatTriggerSummary } from "@/lib/format";

interface AgentCardProps {
  agent: AgentSummary;
  selected: boolean;
  onSelect: (id: string) => void;
}

export function AgentCard({ agent, selected, onSelect }: AgentCardProps) {
  const budgetRatio =
    agent.max_runs_per_day > 0
      ? Math.min(agent.runs_today / agent.max_runs_per_day, 1)
      : 0;

  return (
    <button
      type="button"
      onClick={() => onSelect(agent.id)}
      className={cn(
        "w-full text-left rounded-lg border p-3 transition-colors",
        selected
          ? "border-primary bg-primary/10"
          : "border-border bg-card hover:border-primary/40"
      )}
    >
      <div className="flex items-center gap-2 mb-1">
        <StatusDot status={agent.last_run_status} />
        <span className="font-display text-sm truncate">{agent.name}</span>
      </div>
      <div className="flex items-center gap-1.5 mb-2">
        <Badge variant="outline" className="text-[10px]">
          {agent.template}
        </Badge>
      </div>
      <div className="text-xs text-muted-foreground font-mono space-y-0.5">
        <div className="truncate">{agent.owner}</div>
        {agent.triggers.length > 0 && (
          <div className="truncate">{formatTriggerSummary(agent.triggers)}</div>
        )}
        {agent.last_run_at && (
          <div className="truncate">{relativeTime(agent.last_run_at)}</div>
        )}
      </div>
      {agent.max_runs_per_day > 0 && (
        <div className="mt-2">
          <div className="flex justify-between text-[10px] text-muted-foreground mb-0.5">
            <span>runs</span>
            <span>{agent.runs_today}/{agent.max_runs_per_day}</span>
          </div>
          <div className="h-1 rounded-full bg-muted overflow-hidden">
            <div
              className="h-full rounded-full bg-primary transition-all"
              style={{ width: `${budgetRatio * 100}%` }}
            />
          </div>
        </div>
      )}
    </button>
  );
}
