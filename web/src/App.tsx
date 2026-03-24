import { useState, useCallback, useMemo } from "react";
import { useAgents } from "@/hooks/use-agents";
import { useTemplates } from "@/hooks/use-templates";
import type { AgentSummary } from "@/lib/types";
import { AgentCard } from "@/components/agent-card";
import { AgentDetail } from "@/components/agent-detail";
import { NewAgentDialog } from "@/components/new-agent-dialog";
import { TemplateDetailView } from "@/components/template-detail";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { PlusIcon, SettingsIcon } from "lucide-react";

type View =
  | { kind: "empty" }
  | { kind: "agent"; id: string }
  | { kind: "template"; id: string };

function App() {
  const { agents, loading, error, refetch } = useAgents();
  const { templates } = useTemplates();
  const [view, setView] = useState<View>({ kind: "empty" });
  const [showNewAgent, setShowNewAgent] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [groupBy, setGroupBy] = useState<"flat" | "owner" | "template">("flat");

  const groupedAgents = useMemo(() => {
    const query = searchQuery.toLowerCase().trim();
    const filtered = query
      ? agents.filter(
          (a) =>
            a.name.toLowerCase().includes(query) ||
            a.owner.toLowerCase().includes(query) ||
            a.template.toLowerCase().includes(query)
        )
      : agents;

    if (groupBy === "flat") {
      return [{ label: null, agents: filtered }];
    }

    const map = new Map<string, AgentSummary[]>();
    for (const agent of filtered) {
      const key = groupBy === "owner" ? agent.owner : agent.template;
      const bucket = map.get(key);
      if (bucket) {
        bucket.push(agent);
      } else {
        map.set(key, [agent]);
      }
    }

    return Array.from(map.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([label, agents]) => ({ label, agents }));
  }, [agents, searchQuery, groupBy]);

  const handleAgentCreated = useCallback(
    (agentId: string) => {
      setView({ kind: "agent", id: agentId });
      refetch();
    },
    [refetch]
  );

  const selectedAgentId = view.kind === "agent" ? view.id : null;

  return (
    <div className="flex h-screen bg-background text-foreground">
      {/* Sidebar */}
      <div className="w-72 border-r flex flex-col shrink-0">
        <div className="h-12 flex items-center gap-2 px-4 border-b shrink-0">
          <span className="font-display text-primary text-lg">Clarion</span>
          <span className="text-xs text-muted-foreground">intelligence platform</span>
        </div>
        <div className="px-3 py-2 border-b space-y-2 shrink-0">
          <Input
            placeholder="Search agents..."
            value={searchQuery}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setSearchQuery(e.target.value)}
            className="h-7 text-xs"
          />
          <div className="flex items-center gap-1">
            <span className="text-[10px] text-muted-foreground mr-1">Group</span>
            {(["flat", "owner", "template"] as const).map((mode) => (
              <Button
                key={mode}
                size="xs"
                variant={groupBy === mode ? "secondary" : "ghost"}
                onClick={() => setGroupBy(mode)}
                className="text-[10px]"
              >
                {mode === "flat" ? "None" : mode === "owner" ? "Owner" : "Template"}
              </Button>
            ))}
          </div>
        </div>
        <ScrollArea className="flex-1">
          <div className="p-2 space-y-1.5">
            {loading && (
              <div className="text-sm text-muted-foreground px-2 py-4">
                Loading agents...
              </div>
            )}
            {error && (
              <div className="text-sm text-destructive px-2 py-4">{error}</div>
            )}
            {!loading && !error && groupedAgents.every((g: { agents: AgentSummary[] }) => g.agents.length === 0) && (
              <div className="text-sm text-muted-foreground px-2 py-4">
                {searchQuery.trim()
                  ? "No agents match your search"
                  : "No agents yet"}
              </div>
            )}
            {(() => {
              let cardIndex = 0;
              return groupedAgents.map((group: { label: string | null; agents: AgentSummary[] }) => (
                <div key={group.label ?? "__flat__"}>
                  {group.label && (
                    <div className="px-2 pt-3 pb-1 first:pt-0 animate-fade-in">
                      <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                        {group.label}
                      </span>
                    </div>
                  )}
                  {group.agents.map((agent: AgentSummary) => {
                    const i = cardIndex++;
                    return (
                      <div
                        key={agent.id}
                        className="animate-fade-in-up"
                        style={{ animationDelay: `${Math.min(i * 50, 300)}ms` }}
                      >
                        <AgentCard
                          agent={agent}
                          selected={agent.id === selectedAgentId}
                          onSelect={(id) => setView({ kind: "agent", id })}
                        />
                      </div>
                    );
                  })}
                </div>
              ));
            })()}

            {/* Templates section */}
            {templates.length > 0 && (
              <>
                <Separator className="my-2" />
                <div className="px-2 pb-1">
                  <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                    Templates
                  </span>
                </div>
                {templates.map((tmpl, i) => (
                  <div
                    key={tmpl.id}
                    className="animate-fade-in-up"
                    style={{ animationDelay: `${Math.min(i * 50, 300)}ms` }}
                  >
                    <button
                      onClick={() => setView({ kind: "template", id: tmpl.id })}
                      className={`w-full text-left rounded-md px-3 py-2 text-sm transition-colors ${
                        view.kind === "template" && view.id === tmpl.id
                          ? "bg-muted"
                          : "hover:bg-muted/50"
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <SettingsIcon className="size-3 text-muted-foreground" />
                        <span>{tmpl.name}</span>
                        <Badge variant="outline" className="text-[10px] ml-auto">
                          {tmpl.tools.length} tools
                        </Badge>
                      </div>
                    </button>
                  </div>
                ))}
              </>
            )}
          </div>
        </ScrollArea>
      </div>

      {/* Main */}
      <div className="flex-1 flex flex-col min-w-0">
        <div className="h-12 border-b shrink-0 flex items-center justify-end px-4">
          <Button
            size="sm"
            className="bg-amber-500 text-amber-950 hover:bg-amber-400"
            onClick={() => setShowNewAgent(true)}
          >
            <PlusIcon data-icon="inline-start" />
            New agent
          </Button>
        </div>
        <div className="flex-1 overflow-hidden">
          {view.kind === "agent" && (
            <AgentDetail
              key={view.id}
              agentId={view.id}
              onBack={() => setView({ kind: "empty" })}
            />
          )}
          {view.kind === "template" && (
            <TemplateDetailView
              templateId={view.id}
              onBack={() => setView({ kind: "empty" })}
            />
          )}
          {view.kind === "empty" && (
            <div className="flex items-center justify-center h-full text-muted-foreground">
              <div className="text-center">
                <p className="font-display text-lg mb-1">Select an agent</p>
                <p className="text-xs">Pick one from the sidebar to view its runs and mission</p>
              </div>
            </div>
          )}
        </div>
      </div>

      <NewAgentDialog
        open={showNewAgent}
        onOpenChange={setShowNewAgent}
        onCreated={handleAgentCreated}
      />
    </div>
  );
}

export default App;
