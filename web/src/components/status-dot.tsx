import { cn } from "@/lib/utils";

export function StatusDot({ status }: { status: string | null }) {
  const colorClass =
    status === "success"
      ? "bg-green-500"
      : status === "failed"
        ? "bg-red-500"
        : status === "running"
          ? "bg-amber-500 animate-pulse"
          : "bg-muted-foreground";
  return <span className={cn("inline-block size-2 rounded-full shrink-0", colorClass)} />;
}
