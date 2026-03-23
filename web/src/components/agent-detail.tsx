import { useState } from "react";
import { useAgent } from "@/hooks/use-agent";
import { useRuns } from "@/hooks/use-runs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { RunDetailSheet } from "@/components/run-detail";
import { cn } from "@/lib/utils";
import { formatTime, formatDuration, statusColor } from "@/lib/format";
import { ArrowLeftIcon } from "lucide-react";

function StatusDot({ status }: { status: string }) {
  const colorClass =
    status === "success"
      ? "bg-green-500"
      : status === "failed"
        ? "bg-red-500"
        : status === "running"
          ? "bg-amber-500 animate-pulse"
          : "bg-muted-foreground";

  return <span className={cn("inline-block h-2 w-2 rounded-full shrink-0", colorClass)} />;
}

interface AgentDetailProps {
  agentId: string;
  onBack: () => void;
}

export function AgentDetail({ agentId, onBack }: AgentDetailProps) {
  const { agent, loading, error } = useAgent(agentId);
  const { runs, loading: runsLoading } = useRuns(agentId);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground">
        Loading agent...
      </div>
    );
  }

  if (error || !agent) {
    return (
      <div className="flex items-center justify-center h-full text-destructive">
        {error ?? "Agent not found"}
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-3 px-4 py-3 border-b">
        <Button variant="ghost" size="icon-sm" onClick={onBack}>
          <ArrowLeftIcon />
        </Button>
        <h2 className="font-display text-xl">{agent.name}</h2>
        <Badge variant="outline">{agent.template}</Badge>
        {agent.last_run_status && (
          <Badge variant="secondary" className={statusColor(agent.last_run_status)}>
            {agent.last_run_status}
          </Badge>
        )}
      </div>

      <div className="flex items-center gap-4 px-4 py-2 text-xs text-muted-foreground border-b">
        <span>owner: {agent.owner}</span>
        {agent.schedule_cron && <span>schedule: {agent.schedule_cron}</span>}
        {agent.schedule_timezone && <span>tz: {agent.schedule_timezone}</span>}
        <span>runs today: {agent.runs_today}/{agent.max_runs_per_day}</span>
        <span>model: {agent.model}</span>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        <Tabs defaultValue="runs">
          <TabsList>
            <TabsTrigger value="runs">Runs</TabsTrigger>
            <TabsTrigger value="mission">Mission</TabsTrigger>
            <TabsTrigger value="outputs">Outputs</TabsTrigger>
          </TabsList>

          <TabsContent value="runs">
            <div className="space-y-2 mt-3">
              {runsLoading && (
                <div className="text-muted-foreground text-sm">Loading runs...</div>
              )}
              {!runsLoading && runs.length === 0 && (
                <div className="text-muted-foreground text-sm">No runs yet</div>
              )}
              {runs.map((run) => (
                <button
                  key={run.run_id}
                  type="button"
                  onClick={() => setSelectedRunId(run.run_id)}
                  className="w-full text-left"
                >
                  <Card className="hover:border-primary/40 transition-colors cursor-pointer">
                    <CardContent>
                      <div className="flex items-center gap-3">
                        <StatusDot status={run.status} />
                        <span className="text-sm">{formatTime(run.started_at)}</span>
                        <Badge variant="outline" className="text-[10px]">
                          {run.trigger}
                        </Badge>
                        <span className="text-xs text-muted-foreground ml-auto">
                          {formatDuration(run.started_at, run.completed_at)}
                        </span>
                      </div>
                      {Object.keys(run.tool_call_counts).length > 0 && (
                        <div className="flex gap-1.5 mt-2 flex-wrap">
                          {Object.entries(run.tool_call_counts).map(([tool, count]) => (
                            <Badge key={tool} variant="secondary" className="text-[10px]">
                              {tool}: {count}
                            </Badge>
                          ))}
                        </div>
                      )}
                    </CardContent>
                  </Card>
                </button>
              ))}
            </div>
          </TabsContent>

          <TabsContent value="mission">
            <Card className="mt-3">
              <CardContent>
                <pre className="whitespace-pre-wrap font-display text-sm leading-relaxed">
                  {agent.mission_md}
                </pre>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="outputs">
            <div className="space-y-2 mt-3">
              {agent.outputs.length === 0 && (
                <div className="text-muted-foreground text-sm">No outputs defined</div>
              )}
              {agent.outputs.map((output) => (
                <Card key={output.name}>
                  <CardHeader>
                    <CardTitle>{output.name}</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p className="text-sm text-muted-foreground mb-2">{output.description}</p>
                    <div className="flex gap-1.5 flex-wrap">
                      <Badge variant="outline" className="text-[10px]">
                        trigger: {output.trigger}
                      </Badge>
                      <Badge variant="outline" className="text-[10px]">
                        type: {output.type}
                      </Badge>
                      <Badge variant="secondary" className="text-[10px]">
                        {output.destination}
                      </Badge>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </TabsContent>
        </Tabs>
      </div>

      <RunDetailSheet
        agentId={agentId}
        runId={selectedRunId}
        open={selectedRunId !== null}
        onOpenChange={(open) => {
          if (!open) setSelectedRunId(null);
        }}
      />
    </div>
  );
}
