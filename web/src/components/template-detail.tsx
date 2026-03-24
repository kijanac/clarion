import { useState, useCallback } from "react";
import { useTemplate } from "@/hooks/use-template";
import { apiPut } from "@/lib/api";
import type { TemplateDetail } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { ArrowLeftIcon, PencilIcon, SaveIcon, XIcon } from "lucide-react";

const RESOURCE_LABELS: Record<string, string> = {
  max_runs_per_day: "Max runs / day",
  max_search_calls_per_run: "Search calls / run",
  max_fetch_calls_per_run: "Fetch calls / run",
  max_deep_research_calls_per_run: "Deep research / run",
  max_sql_calls_per_run: "SQL calls / run",
  run_timeout_seconds: "Run timeout (s)",
  max_database_mb: "Max database (MB)",
  max_self_scheduled_runs_per_day: "Self-scheduled runs / day",
};

interface TemplateDetailProps {
  templateId: string;
  onBack: () => void;
}

export function TemplateDetailView({ templateId, onBack }: TemplateDetailProps) {
  const { template, loading, error, refetch } = useTemplate(templateId);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  const [draftModel, setDraftModel] = useState("");
  const [draftMaxTokens, setDraftMaxTokens] = useState(8192);
  const [draftPrompt, setDraftPrompt] = useState("");
  const [draftTools, setDraftTools] = useState("");
  const [draftResources, setDraftResources] = useState<Record<string, number>>({});

  const startEditing = useCallback((tmpl: TemplateDetail) => {
    setDraftModel(tmpl.model);
    setDraftMaxTokens(tmpl.max_tokens);
    setDraftPrompt(tmpl.system_prompt);
    setDraftTools(tmpl.tools.join("\n"));
    setDraftResources({ ...tmpl.resources });
    setSaveError(null);
    setEditing(true);
  }, []);

  const cancelEditing = useCallback(() => {
    setEditing(false);
    setSaveError(null);
  }, []);

  const handleSave = useCallback(async () => {
    setSaving(true);
    setSaveError(null);
    try {
      const tools = draftTools
        .split("\n")
        .map((t) => t.trim())
        .filter(Boolean);
      await apiPut(`/api/templates/${templateId}`, {
        model: draftModel,
        max_tokens: draftMaxTokens,
        system_prompt: draftPrompt,
        tools,
        resources: draftResources,
      });
      setEditing(false);
      setSaveSuccess(true);
      refetch();
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err: unknown) {
      setSaveError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }, [templateId, draftModel, draftMaxTokens, draftPrompt, draftTools, draftResources, refetch]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground">
        Loading template...
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full text-destructive">
        {error}
      </div>
    );
  }

  if (!template) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground">
        Loading template...
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="px-4 pt-4 pb-3 border-b space-y-2 shrink-0">
        <button
          onClick={onBack}
          className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeftIcon className="size-3" />
          templates
        </button>
        <div className="flex items-center gap-3">
          <h2 className="font-display text-xl">{template.name}</h2>
          <Badge variant="outline">{template.id}</Badge>
          {!editing && (
            <Button
              variant="ghost"
              size="sm"
              className="ml-auto"
              onClick={() => startEditing(template)}
            >
              <PencilIcon className="size-3 mr-1" />
              Edit
            </Button>
          )}
          {editing && (
            <div className="ml-auto flex gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={cancelEditing}
                disabled={saving}
              >
                <XIcon className="size-3 mr-1" />
                Cancel
              </Button>
              <Button
                size="sm"
                onClick={handleSave}
                disabled={saving}
              >
                <SaveIcon className="size-3 mr-1" />
                {saving ? "Saving..." : "Save"}
              </Button>
            </div>
          )}
        </div>
        {saveSuccess && (
          <p className="text-xs text-green-500">Template saved. Changes take effect on next agent run.</p>
        )}
        {saveError && (
          <p className="text-xs text-destructive">{saveError}</p>
        )}
        <p className="text-sm text-muted-foreground">{template.description}</p>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        {/* Model */}
        <div className="space-y-1.5">
          <Label>Model</Label>
          {editing ? (
            <Input
              value={draftModel}
              onChange={(e) => setDraftModel(e.target.value)}
            />
          ) : (
            <p className="text-sm font-mono">{template.model}</p>
          )}
        </div>

        {/* Max tokens */}
        <div className="space-y-1.5">
          <Label>Max tokens</Label>
          {editing ? (
            <Input
              type="number"
              value={draftMaxTokens}
              onChange={(e) => setDraftMaxTokens(parseInt(e.target.value) || 0)}
            />
          ) : (
            <p className="text-sm font-mono">{template.max_tokens}</p>
          )}
        </div>

        <Separator />

        {/* Tools */}
        <div className="space-y-1.5">
          <Label>Tools</Label>
          {editing ? (
            <div className="space-y-1">
              <Textarea
                value={draftTools}
                onChange={(e) => setDraftTools(e.target.value)}
                rows={6}
                className="font-mono text-xs"
                placeholder="One tool per line"
              />
              <p className="text-[10px] text-muted-foreground">One tool per line</p>
            </div>
          ) : (
            <div className="flex gap-1.5 flex-wrap">
              {template.tools.map((tool) => (
                <Badge key={tool} variant="secondary" className="text-xs">
                  {tool}
                </Badge>
              ))}
            </div>
          )}
        </div>

        <Separator />

        {/* Resources */}
        <div className="space-y-3">
          <Label>Resource limits</Label>
          {editing ? (
            <div className="grid grid-cols-2 gap-3">
              {Object.entries(draftResources).map(([key, value]) => (
                <div key={key} className="space-y-1">
                  <label className="text-[10px] text-muted-foreground">
                    {RESOURCE_LABELS[key] ?? key}
                  </label>
                  <Input
                    type="number"
                    value={value}
                    onChange={(e) =>
                      setDraftResources((prev) => ({
                        ...prev,
                        [key]: parseInt(e.target.value) || 0,
                      }))
                    }
                    className="h-8 text-xs font-mono"
                  />
                </div>
              ))}
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-2">
              {Object.entries(template.resources).map(([key, value]) => (
                <Card key={key} className="bg-muted/20">
                  <CardContent className="py-2 px-3">
                    <div className="text-[10px] text-muted-foreground">
                      {RESOURCE_LABELS[key] ?? key}
                    </div>
                    <div className="text-sm font-mono">{value}</div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </div>

        <Separator />

        {/* System prompt */}
        <div className="space-y-1.5">
          <Label>System prompt</Label>
          {editing ? (
            <Textarea
              value={draftPrompt}
              onChange={(e) => setDraftPrompt(e.target.value)}
              rows={20}
              className="font-mono text-xs"
            />
          ) : (
            <Card className="bg-muted/20">
              <CardContent>
                <pre className="whitespace-pre-wrap text-xs font-mono text-muted-foreground leading-relaxed">
                  {template.system_prompt}
                </pre>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
