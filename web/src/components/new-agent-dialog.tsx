import { useState, useCallback } from "react";
import { useTemplates } from "@/hooks/use-templates";
import { useAgents } from "@/hooks/use-agents";
import { apiPost } from "@/lib/api";
import type { Template, TriggerDefinition, AgentSummary } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { TriggerEditor } from "@/components/trigger-editor";
import { cn } from "@/lib/utils";

interface NewAgentDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (agentId: string) => void;
}

interface FormData {
  templateId: string;
  name: string;
  owner: string;
  mission: string;
  triggers: TriggerDefinition[];
}

function initialFormData(): FormData {
  return {
    templateId: "",
    name: "",
    owner: "",
    mission: "",
    triggers: [{ type: "cron", expression: "0 6 * * 1", timezone: Intl.DateTimeFormat().resolvedOptions().timeZone }],
  };
}

function TemplateGrid({
  templates,
  loading,
  error,
  selectedId,
  onSelect,
}: {
  templates: Template[];
  loading: boolean;
  error: string | null;
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  if (loading) {
    return <div className="text-sm text-muted-foreground py-4">Loading templates...</div>;
  }
  if (error) {
    return <div className="text-sm text-destructive py-4">{error}</div>;
  }
  if (templates.length === 0) {
    return <div className="text-sm text-muted-foreground py-4">No templates found. Add templates to the server to get started.</div>;
  }
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
      {templates.map((tmpl) => (
        <button
          key={tmpl.id}
          type="button"
          onClick={() => onSelect(tmpl.id)}
          className="text-left"
        >
          <Card
            className={cn(
              "transition-colors cursor-pointer hover:border-primary/40",
              selectedId === tmpl.id && "border-primary ring-2 ring-primary/30"
            )}
          >
            <CardContent className="space-y-2">
              <div className="font-medium text-sm">{tmpl.name}</div>
              <p className="text-xs text-muted-foreground leading-relaxed">
                {tmpl.description}
              </p>
              <div className="flex gap-1 flex-wrap">
                {tmpl.tools.map((tool) => (
                  <Badge key={tool} variant="secondary" className="text-[10px]">
                    {tool}
                  </Badge>
                ))}
              </div>
            </CardContent>
          </Card>
        </button>
      ))}
    </div>
  );
}

function StepMission({
  form,
  onChange,
}: {
  form: FormData;
  onChange: (patch: Partial<FormData>) => void;
}) {
  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor="agent-name">Agent name</Label>
        <Input
          id="agent-name"
          value={form.name}
          onChange={(e) => onChange({ name: e.target.value })}
          placeholder="e.g. weekly-market-report"
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="agent-owner">Owner / team</Label>
        <Input
          id="agent-owner"
          value={form.owner}
          onChange={(e) => onChange({ owner: e.target.value })}
          placeholder="e.g. research-team"
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="agent-mission">Mission</Label>
        <Textarea
          id="agent-mission"
          rows={12}
          value={form.mission}
          onChange={(e) => onChange({ mission: e.target.value })}
          placeholder="I work on [domain] for our team. I need to track..."
        />
        <p className="text-xs text-muted-foreground">
          Write this like you're briefing a new, highly capable colleague.
        </p>
      </div>
    </div>
  );
}

function StepConfigure({
  form,
  onChange,
  selectedTemplate,
  existingAgents,
}: {
  form: FormData;
  onChange: (patch: Partial<FormData>) => void;
  selectedTemplate: Template | undefined;
  existingAgents: AgentSummary[];
}) {
  const missionPreview =
    form.mission.length > 120 ? form.mission.slice(0, 120) + "..." : form.mission;

  return (
    <div className="space-y-4">
      <TriggerEditor
        triggers={form.triggers}
        onChange={(triggers) => onChange({ triggers })}
        agents={existingAgents}
      />

      <Card className="bg-muted/30">
        <CardContent className="space-y-2">
          <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
            Summary
          </div>
          {selectedTemplate && (
            <div className="flex items-center gap-2">
              <Badge variant="outline">{selectedTemplate.name}</Badge>
            </div>
          )}
          <div className="text-sm font-medium">{form.name}</div>
          <p className="text-xs text-muted-foreground leading-relaxed">
            {missionPreview}
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

export function NewAgentDialog({ open, onOpenChange, onCreated }: NewAgentDialogProps) {
  const { templates, loading: templatesLoading, error: templatesError } = useTemplates();
  const { agents: existingAgents } = useAgents();
  const [step, setStep] = useState(1);
  const [form, setForm] = useState<FormData>(initialFormData);
  const [deploying, setDeploying] = useState(false);
  const [deployError, setDeployError] = useState<string | null>(null);

  const selectedTemplate = templates.find((t) => t.id === form.templateId);

  const updateForm = useCallback((patch: Partial<FormData>) => {
    setForm((prev) => ({ ...prev, ...patch }));
  }, []);

  const canContinue =
    step === 1
      ? form.templateId !== ""
      : step === 2
        ? form.name.trim() !== "" && form.owner.trim() !== "" && form.mission.trim() !== ""
        : true;

  const handleDeploy = useCallback(async () => {
    setDeploying(true);
    setDeployError(null);
    try {
      const result = await apiPost<{ id: string }>("/api/agents", {
        name: form.name.trim(),
        description: selectedTemplate?.description ?? "",
        owner: form.owner.trim(),
        template: form.templateId,
        mission: form.mission.trim(),
        triggers: form.triggers,
      });
      onCreated(result.id);
      onOpenChange(false);
      setStep(1);
      setForm(initialFormData());
    } catch (err: unknown) {
      setDeployError(err instanceof Error ? err.message : "Couldn't create agent. Check the form and try again.");
    } finally {
      setDeploying(false);
    }
  }, [form, selectedTemplate, onCreated, onOpenChange]);

  const handleOpenChange = useCallback(
    (next: boolean) => {
      onOpenChange(next);
      if (!next) {
        setStep(1);
        setForm(initialFormData());
        setDeployError(null);
      }
    },
    [onOpenChange]
  );

  const progressPercent = Math.round((step / 3) * 100);

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-lg">
        {/* Progress bar */}
        <div className="absolute top-0 left-0 right-0 h-0.5 bg-muted rounded-t-xl overflow-hidden">
          <div
            className="h-full bg-amber-500 transition-all duration-300"
            style={{ width: `${progressPercent}%` }}
          />
        </div>

        <DialogHeader>
          <div className="flex items-center justify-between">
            <DialogTitle>New agent</DialogTitle>
            <span className="text-xs text-muted-foreground">
              Step {step} of 3
            </span>
          </div>
          <DialogDescription>
            {step === 1 && "Choose a template to start from."}
            {step === 2 && "Define the agent's identity and mission."}
            {step === 3 && "Review and create your agent."}
          </DialogDescription>
        </DialogHeader>

        <div className="min-h-[280px]">
          {step === 1 && (
            <TemplateGrid
              templates={templates}
              loading={templatesLoading}
              error={templatesError}
              selectedId={form.templateId}
              onSelect={(id) => updateForm({ templateId: id })}
            />
          )}
          {step === 2 && <StepMission form={form} onChange={updateForm} />}
          {step === 3 && (
            <StepConfigure
              form={form}
              onChange={updateForm}
              selectedTemplate={selectedTemplate}
              existingAgents={existingAgents}
            />
          )}
        </div>

        {deployError && (
          <p className="text-sm text-destructive">{deployError}</p>
        )}

        <DialogFooter>
          {step > 1 && (
            <Button variant="outline" onClick={() => setStep((s) => s - 1)} disabled={deploying}>
              Back
            </Button>
          )}
          {step < 3 ? (
            <Button onClick={() => setStep((s) => s + 1)} disabled={!canContinue}>
              Continue
            </Button>
          ) : (
            <Button onClick={handleDeploy} disabled={deploying}>
              {deploying ? "Creating..." : "Create agent"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
