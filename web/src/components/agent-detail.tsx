import { useState, useCallback } from "react";
import { useAgent } from "@/hooks/use-agent";
import { useRuns } from "@/hooks/use-runs";
import { apiPost, apiPut } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { RunDetailSheet } from "@/components/run-detail";
import { StatusDot } from "@/components/status-dot";
import { formatTime, formatDuration, statusColor } from "@/lib/format";
import { ArrowLeftIcon, PlayIcon, PencilIcon } from "lucide-react";

interface AgentDetailProps {
  agentId: string;
  onBack: () => void;
}

export function AgentDetail({ agentId, onBack }: AgentDetailProps) {
  const { agent, loading, error, refetch: refetchAgent } = useAgent(agentId);
  const { runs, loading: runsLoading, refetch: refetchRuns } = useRuns(agentId);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [runningNow, setRunningNow] = useState(false);
  const [activeTab, setActiveTab] = useState("runs");
  const [editingMission, setEditingMission] = useState(false);
  const [missionDraft, setMissionDraft] = useState("");
  const [savingMission, setSavingMission] = useState(false);
  const [missionSuccess, setMissionSuccess] = useState(false);
  const [missionError, setMissionError] = useState<string | null>(null);

  const handleRunNow = useCallback(async () => {
    setRunningNow(true);
    try {
      await apiPost(`/api/agents/${agentId}/run`, {});
      setTimeout(() => {
        refetchRuns();
      }, 2000);
    } catch {
      // Run trigger failed silently — the run list will reflect the state
    } finally {
      setRunningNow(false);
    }
  }, [agentId, refetchRuns]);

  const handleSaveMission = useCallback(async () => {
    setSavingMission(true);
    setMissionError(null);
    try {
      await apiPut(`/api/agents/${agentId}/mission`, { mission: missionDraft });
      setEditingMission(false);
      setMissionSuccess(true);
      refetchAgent();
      setTimeout(() => setMissionSuccess(false), 3000);
    } catch (err: unknown) {
      setMissionError(err instanceof Error ? err.message : "Couldn't save mission. Try again.");
    } finally {
      setSavingMission(false);
    }
  }, [agentId, missionDraft, refetchAgent]);

  const handleCancelEdit = useCallback(() => {
    setEditingMission(false);
    setMissionError(null);
    if (agent) {
      setMissionDraft(agent.mission_md);
    }
  }, [agent]);

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
        {error ?? "Agent not found. It may have been removed."}
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full animate-fade-in">
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
        <div className="ml-auto">
          <Button
            variant="outline"
            size="sm"
            className="text-primary"
            onClick={handleRunNow}
            disabled={runningNow}
          >
            <PlayIcon data-icon="inline-start" />
            {runningNow ? "Running..." : "Run now"}
          </Button>
        </div>
      </div>

      {agent.mission_md && (
        <button
          type="button"
          onClick={() => setActiveTab("mission")}
          className="block w-full text-left px-4 py-2.5 border-b border-l-2 border-l-primary/40 hover:border-l-primary hover:bg-muted/30 transition-colors cursor-pointer"
        >
          <p className="font-display text-sm leading-relaxed text-foreground/70 line-clamp-2">
            {agent.mission_md}
          </p>
        </button>
      )}

      <div className="flex items-center gap-4 px-4 py-2 text-xs text-muted-foreground border-b flex-wrap">
        <span>owner: {agent.owner}</span>
        {agent.triggers.map((trigger, i) => (
          <span key={i}>
            {trigger.type === "cron"
              ? `cron: ${trigger.expression}`
              : `when ${trigger.source_agent} produces ${trigger.output_name}`}
          </span>
        ))}
        {agent.timezone && <span>timezone: {agent.timezone}</span>}
        <span>runs today: {agent.runs_today}/{agent.max_runs_per_day}</span>
        <span>model: {agent.model}</span>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        <Tabs value={activeTab} onValueChange={(val) => setActiveTab(val as string)}>
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
                <div className="text-muted-foreground text-sm">No runs yet. Click "Run now" to start one.</div>
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
            <Card className="mt-3 relative">
              <CardContent>
                {!editingMission && (
                  <Button
                    variant="ghost"
                    size="xs"
                    className="absolute top-3 right-3"
                    onClick={() => {
                      setMissionDraft(agent.mission_md);
                      setEditingMission(true);
                      setMissionError(null);
                    }}
                  >
                    <PencilIcon data-icon="inline-start" />
                    Edit
                  </Button>
                )}
                {editingMission ? (
                  <div className="space-y-3">
                    <Textarea
                      rows={12}
                      value={missionDraft}
                      onChange={(e) => setMissionDraft(e.target.value)}
                    />
                    {missionError && (
                      <p className="text-sm text-destructive animate-fade-in">{missionError}</p>
                    )}
                    <div className="flex gap-2 justify-end">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={handleCancelEdit}
                        disabled={savingMission}
                      >
                        Cancel
                      </Button>
                      <Button
                        size="sm"
                        onClick={handleSaveMission}
                        disabled={savingMission}
                      >
                        {savingMission ? "Saving..." : "Save"}
                      </Button>
                    </div>
                  </div>
                ) : (
                  <>
                    <pre className="whitespace-pre-wrap font-display text-sm leading-relaxed">
                      {agent.mission_md}
                    </pre>
                    {missionSuccess && (
                      <p className="text-sm text-green-600 mt-2 animate-fade-in">Mission saved.</p>
                    )}
                  </>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="outputs">
            <div className="space-y-2 mt-3">
              {agent.outputs.length === 0 && (
                <div className="text-muted-foreground text-sm">No outputs configured for this agent</div>
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
