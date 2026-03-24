import { useCallback } from "react";
import type { TriggerDefinition, AgentSummary } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SchedulePicker } from "@/components/schedule-picker";
import { XIcon, PlusIcon } from "lucide-react";

interface TriggerEditorProps {
  triggers: TriggerDefinition[];
  onChange: (triggers: TriggerDefinition[]) => void;
  agents: AgentSummary[];
}

function TriggerCard({
  trigger,
  index,
  onUpdate,
  onRemove,
  agents,
}: {
  trigger: TriggerDefinition;
  index: number;
  onUpdate: (index: number, trigger: TriggerDefinition) => void;
  onRemove: (index: number) => void;
  agents: AgentSummary[];
}) {
  return (
    <Card size="sm">
      <CardContent>
        <div className="flex items-start justify-between gap-2">
          <div className="flex-1 space-y-3">
            <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
              {trigger.type === "cron" ? "Schedule" : "When another agent produces output"}
            </div>

            {trigger.type === "cron" && (
              <SchedulePicker
                cron={trigger.expression ?? ""}
                onCronChange={(expression) =>
                  onUpdate(index, { ...trigger, expression })
                }
              />
            )}

            {trigger.type === "agent_output" && (
              <div className="space-y-3">
                <div className="space-y-1.5">
                  <Label>Source agent</Label>
                  <Select
                    value={trigger.source_agent ?? ""}
                    onValueChange={(value) =>
                      onUpdate(index, { ...trigger, source_agent: value ?? "" })
                    }
                  >
                    <SelectTrigger className="w-full">
                      <SelectValue placeholder="Select an agent..." />
                    </SelectTrigger>
                    <SelectContent>
                      {agents.map((agent) => (
                        <SelectItem key={agent.id} value={agent.id}>
                          {agent.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor={`output-name-${index}`}>Output name</Label>
                  <Input
                    id={`output-name-${index}`}
                    value={trigger.output_name ?? ""}
                    onChange={(e) =>
                      onUpdate(index, { ...trigger, output_name: e.target.value })
                    }
                    placeholder="e.g. weekly-briefing"
                  />
                </div>
              </div>
            )}
          </div>

          <Button
            variant="ghost"
            size="icon-xs"
            onClick={() => onRemove(index)}
            aria-label="Remove trigger"
          >
            <XIcon />
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export function TriggerEditor({ triggers, onChange, agents }: TriggerEditorProps) {
  const handleUpdate = useCallback(
    (index: number, updated: TriggerDefinition) => {
      const next = triggers.map((t, i) => (i === index ? updated : t));
      onChange(next);
    },
    [triggers, onChange],
  );

  const handleRemove = useCallback(
    (index: number) => {
      onChange(triggers.filter((_, i) => i !== index));
    },
    [triggers, onChange],
  );

  const handleAdd = useCallback(
    (type: "cron" | "agent_output") => {
      const newTrigger: TriggerDefinition =
        type === "cron"
          ? { type: "cron", expression: "0 6 * * 1" }
          : { type: "agent_output", source_agent: "", output_name: "" };
      onChange([...triggers, newTrigger]);
    },
    [triggers, onChange],
  );

  return (
    <div className="space-y-3">
      <Label>Triggers</Label>

      {triggers.map((trigger, index) => (
        <TriggerCard
          key={index}
          trigger={trigger}
          index={index}
          onUpdate={handleUpdate}
          onRemove={handleRemove}
          agents={agents}
        />
      ))}

      {triggers.length === 0 && (
        <p className="text-xs text-muted-foreground">
          No triggers configured. Add one below.
        </p>
      )}

      <div className="flex gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => handleAdd("cron")}
        >
          <PlusIcon data-icon="inline-start" />
          Add schedule
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => handleAdd("agent_output")}
        >
          <PlusIcon data-icon="inline-start" />
          Add agent output trigger
        </Button>
      </div>
    </div>
  );
}
