import cronstrue from "cronstrue";

export function formatTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  }) + ", " + d.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

export function formatDuration(start: string, end: string | null): string {
  if (!end) return "running...";
  const ms = new Date(end).getTime() - new Date(start).getTime();
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes === 0) return `${seconds}s`;
  return `${minutes}m ${seconds}s`;
}

export function statusColor(status: string): string {
  switch (status) {
    case "success":
      return "text-green-500";
    case "failed":
      return "text-red-500";
    case "running":
      return "text-amber-500";
    default:
      return "text-muted-foreground";
  }
}

export function humanCron(expression: string): string {
  try {
    return cronstrue.toString(expression, { use24HourTimeFormat: false });
  } catch {
    return expression;
  }
}

export function formatTriggerSummary(triggers: { type: string; expression?: string; timezone?: string; source_agent?: string; output_name?: string }[]): string {
  return triggers
    .map((t) => {
      if (t.type === "cron" && t.expression) {
        const desc = humanCron(t.expression);
        return t.timezone && t.timezone !== "UTC" ? `${desc} (${t.timezone})` : desc;
      }
      if (t.type === "agent_output") return `when ${t.source_agent} produces ${t.output_name}`;
      return t.type;
    })
    .join(", ");
}

export function relativeTime(iso: string): string {
  const now = Date.now();
  const then = new Date(iso).getTime();
  const diffMs = now - then;
  const diffSeconds = Math.floor(diffMs / 1000);
  const diffMinutes = Math.floor(diffSeconds / 60);
  const diffHours = Math.floor(diffMinutes / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffSeconds < 60) return "just now";
  if (diffMinutes < 60) return `${diffMinutes} minute${diffMinutes === 1 ? "" : "s"} ago`;
  if (diffHours < 24) return `${diffHours} hour${diffHours === 1 ? "" : "s"} ago`;
  return `${diffDays} day${diffDays === 1 ? "" : "s"} ago`;
}
