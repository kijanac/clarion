import { useCallback } from "react";
import { useAgent } from "@/hooks/use-agent";
import type { TriggerDefinition, AgentSummary } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SchedulePicker } from "@/components/schedule-picker";
import { TimezonePicker } from "@/components/timezone-picker";
import { XIcon, PlusIcon } from "lucide-react";

function AgentOutputFields({
  trigger,
  index,
  onUpdate,
  agents,
}: {
  trigger: TriggerDefinition;
  index: number;
  onUpdate: (index: number, trigger: TriggerDefinition) => void;
  agents: AgentSummary[];
}) {
  const { agent: sourceAgent } = useAgent(trigger.source_agent || null);
  const availableOutputs = sourceAgent?.outputs ?? [];

  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        <Label>Source agent</Label>
        <Select
          value={trigger.source_agent ?? ""}
          onValueChange={(value) =>
            onUpdate(index, { ...trigger, source_agent: value ?? "", output_name: "" })
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
        <Label>Output</Label>
        {availableOutputs.length > 0 ? (
          <Select
            value={trigger.output_name ?? ""}
            onValueChange={(value) =>
              onUpdate(index, { ...trigger, output_name: value ?? "" })
            }
          >
            <SelectTrigger className="w-full">
              <SelectValue placeholder="Select an output..." />
            </SelectTrigger>
            <SelectContent>
              {availableOutputs.map((output) => (
                <SelectItem key={output.name} value={output.name}>
                  {output.name}
                  {output.description && (
                    <span className="text-muted-foreground ml-2">— {output.description}</span>
                  )}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : trigger.source_agent ? (
          <p className="text-xs text-muted-foreground py-1">
            This agent has no outputs configured.
          </p>
        ) : (
          <p className="text-xs text-muted-foreground py-1">
            Select a source agent first.
          </p>
        )}
      </div>
    </div>
  );
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
              <div className="space-y-3">
                <SchedulePicker
                  cron={trigger.expression ?? ""}
                  onCronChange={(expression) =>
                    onUpdate(index, { ...trigger, expression })
                  }
                />
                <div className="space-y-1.5">
                  <Label>Timezone</Label>
                  <TimezonePicker
                    value={trigger.timezone ?? "UTC"}
                    onChange={(tz) => onUpdate(index, { ...trigger, timezone: tz })}
                  />
                </div>
              </div>
            )}

            {trigger.type === "agent_output" && (
              <AgentOutputFields
                trigger={trigger}
                index={index}
                onUpdate={onUpdate}
                agents={agents}
              />
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

interface TriggerEditorProps {
  triggers: TriggerDefinition[];
  onChange: (triggers: TriggerDefinition[]) => void;
  agents: AgentSummary[];
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
          ? { type: "cron", expression: "0 6 * * 1", timezone: Intl.DateTimeFormat().resolvedOptions().timeZone }
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
