import { useState } from "react";
import { useAgents } from "@/hooks/use-agents";
import { AgentCard } from "@/components/agent-card";
import { AgentDetail } from "@/components/agent-detail";
import { ScrollArea } from "@/components/ui/scroll-area";

function App() {
  const { agents, loading, error } = useAgents();
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);

  return (
    <div className="flex h-screen bg-background text-foreground">
      {/* Sidebar */}
      <div className="w-72 border-r flex flex-col shrink-0">
        <div className="h-12 flex items-center gap-2 px-4 border-b shrink-0">
          <span className="font-display text-primary text-lg">Clarion</span>
          <span className="text-xs text-muted-foreground">intelligence platform</span>
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
            {agents.map((agent) => (
              <AgentCard
                key={agent.id}
                agent={agent}
                selected={agent.id === selectedAgentId}
                onSelect={setSelectedAgentId}
              />
            ))}
            {!loading && !error && agents.length === 0 && (
              <div className="text-sm text-muted-foreground px-2 py-4">
                No agents configured
              </div>
            )}
          </div>
        </ScrollArea>
      </div>

      {/* Main */}
      <div className="flex-1 flex flex-col min-w-0">
        <div className="h-12 border-b shrink-0" />
        <div className="flex-1 overflow-hidden">
          {selectedAgentId ? (
            <AgentDetail
              agentId={selectedAgentId}
              onBack={() => setSelectedAgentId(null)}
            />
          ) : (
            <div className="flex items-center justify-center h-full text-muted-foreground">
              <div className="text-center">
                <p className="font-display text-lg mb-1">Select an agent</p>
                <p className="text-xs">Choose an agent from the sidebar to view details</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default App;
