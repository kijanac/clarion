import { useState, useMemo } from "react";
import { ChevronRightIcon } from "lucide-react";
import { useRunDetail } from "@/hooks/use-run-detail";
import { Badge } from "@/components/ui/badge";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import { formatTime, formatDuration, statusColor } from "@/lib/format";
import type { ConversationTurn, ToolCall } from "@/lib/types";

// A thought from the agent (text with no tool calls)
function ThoughtBlock({ text }: { text: string }) {
  return (
    <div className="pl-3 border-l-2 border-primary/30 py-2">
      <p className="text-sm italic text-foreground/80">{text}</p>
    </div>
  );
}

// A single tool call paired with its result
function ToolCallBlock({
  call,
  result,
}: {
  call: ToolCall;
  result: ConversationTurn | null;
}) {
  const [open, setOpen] = useState(false);
  const hasArgs = call.arguments && Object.keys(call.arguments).length > 0;
  const argPreview = hasArgs
    ? Object.entries(call.arguments)
        .map(([k, v]) => `${k}=${typeof v === "string" ? v.slice(0, 60) : JSON.stringify(v).slice(0, 60)}`)
        .join(", ")
    : "";

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="flex items-center gap-2 w-full text-left py-1.5 pl-3 border-l-2 border-muted hover:border-muted-foreground transition-colors">
        <ChevronRightIcon
          className={cn("size-3 shrink-0 text-muted-foreground transition-transform", open && "rotate-90")}
        />
        <Badge
          variant={result?.tool_error ? "destructive" : "secondary"}
          className="text-[10px] shrink-0"
        >
          {call.name}
        </Badge>
        {argPreview && (
          <span className="text-[10px] text-muted-foreground truncate">
            {argPreview}
          </span>
        )}
        {result?.tool_error && (
          <span className="text-[10px] text-destructive ml-auto shrink-0">error</span>
        )}
      </CollapsibleTrigger>
      <CollapsibleContent className="pl-3 border-l-2 border-muted pb-1">
        {hasArgs && (
          <div className="mt-1">
            <span className="text-[10px] text-muted-foreground uppercase tracking-wider">arguments</span>
            <pre className="text-[10px] bg-card rounded p-2 mt-0.5 font-mono whitespace-pre-wrap text-muted-foreground overflow-x-auto">
              {JSON.stringify(call.arguments, null, 2)}
            </pre>
          </div>
        )}
        {result?.text && (
          <div className="mt-1.5">
            <span className="text-[10px] text-muted-foreground uppercase tracking-wider">result</span>
            <pre
              className={cn(
                "text-[10px] bg-card rounded p-2 mt-0.5 font-mono whitespace-pre-wrap overflow-x-auto max-h-60 overflow-y-auto",
                result.tool_error ? "text-destructive" : "text-muted-foreground"
              )}
            >
              {result.text}
            </pre>
          </div>
        )}
      </CollapsibleContent>
    </Collapsible>
  );
}

// Group turns into displayable steps: thoughts and paired tool calls
type Step =
  | { type: "thought"; text: string }
  | { type: "tool_call"; call: ToolCall; result: ConversationTurn | null }

function groupTurns(turns: ConversationTurn[]): Step[] {
  const steps: Step[] = [];
  const toolResults = new Map<string, ConversationTurn>();

  // Index tool results by tool_call_id
  for (const turn of turns) {
    if (turn.role === "tool" && turn.tool_call_id) {
      toolResults.set(turn.tool_call_id, turn);
    }
  }

  // Walk assistant turns and pair tool calls with results
  for (const turn of turns) {
    if (turn.role !== "assistant") continue;

    if (turn.text) {
      steps.push({ type: "thought", text: turn.text });
    }

    if (turn.tool_calls) {
      for (const call of turn.tool_calls) {
        steps.push({
          type: "tool_call",
          call,
          result: toolResults.get(call.id) ?? null,
        });
      }
    }
  }

  return steps;
}

interface RunDetailSheetProps {
  agentId: string;
  runId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function RunDetailSheet({
  agentId,
  runId,
  open,
  onOpenChange,
}: RunDetailSheetProps) {
  const { run, loading, error } = useRunDetail(agentId, runId);
  const steps = useMemo(() => run?.turns ? groupTurns(run.turns) : [], [run]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-[80vw] sm:max-w-[80vw] overflow-y-auto">
        <SheetHeader>
          <SheetTitle>
            {loading && "Loading run..."}
            {error && "Couldn't load run details"}
            {run && (
              <span className="font-mono text-sm">{run.run_id}</span>
            )}
          </SheetTitle>
          <SheetDescription>
            {run && (
              <span className="flex items-center gap-2 flex-wrap">
                <Badge variant="secondary" className={statusColor(run.status)}>
                  {run.status}
                </Badge>
                <Badge variant="outline" className="text-[10px]">
                  {run.trigger}
                </Badge>
                <span className="text-xs">
                  {formatTime(run.started_at)} &mdash;{" "}
                  {formatDuration(run.started_at, run.completed_at)}
                </span>
              </span>
            )}
          </SheetDescription>
        </SheetHeader>

        {run?.error && (
          <div className="mx-4 p-3 rounded-md bg-destructive/10 text-destructive text-sm">
            {run.error}
          </div>
        )}

        {run && Object.keys(run.tool_call_counts).length > 0 && (
          <div className="flex gap-1.5 px-4 flex-wrap">
            {Object.entries(run.tool_call_counts).map(([tool, count]) => (
              <Badge key={tool} variant="secondary" className="text-[10px]">
                {tool}: {count}
              </Badge>
            ))}
          </div>
        )}

        <div className="px-4 pb-4 flex flex-col gap-0.5">
          {steps.length > 0 ? (
            steps.map((step, i) =>
              step.type === "thought" ? (
                <ThoughtBlock key={`thought-${i}`} text={step.text} />
              ) : (
                <ToolCallBlock
                  key={`tool-${step.call.id}-${i}`}
                  call={step.call}
                  result={step.result}
                />
              )
            )
          ) : (
            run && !loading && (
              <p className="text-sm text-muted-foreground py-8 text-center">
                No activity recorded for this run.
              </p>
            )
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
