import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const PRESETS = [
  { id: "weekday-morning", label: "Every weekday morning", cron: "0 6 * * 1-5" },
  { id: "daily-morning", label: "Every morning", cron: "0 6 * * *" },
  { id: "weekly-monday", label: "Every Monday morning", cron: "0 6 * * 1" },
  { id: "twice-daily", label: "Twice daily (6am, 6pm)", cron: "0 6,18 * * *" },
  { id: "every-4h", label: "Every 4 hours", cron: "0 */4 * * *" },
  { id: "hourly", label: "Every hour", cron: "0 * * * *" },
  { id: "custom", label: "Custom cron expression", cron: "" },
] as const;

interface SchedulePickerProps {
  cron: string;
  onCronChange: (cron: string) => void;
}

export function SchedulePicker({ cron, onCronChange }: SchedulePickerProps) {
  const matchedPreset = PRESETS.find((p) => p.id !== "custom" && p.cron === cron);
  const presetId = matchedPreset?.id ?? "custom";

  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        <Label>Schedule</Label>
        <Select
          value={presetId}
          onValueChange={(id) => {
            const preset = PRESETS.find((p) => p.id === id);
            if (preset && preset.id !== "custom") {
              onCronChange(preset.cron);
            }
          }}
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {PRESETS.map((p) => (
              <SelectItem key={p.id} value={p.id}>
                {p.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {presetId === "custom" && (
        <div className="space-y-1.5">
          <Label htmlFor="custom-cron">Cron expression</Label>
          <Input
            id="custom-cron"
            value={cron}
            onChange={(e) => onCronChange(e.target.value)}
            placeholder="0 6 * * 1"
            className="font-mono"
          />
          <p className="text-[10px] text-muted-foreground">
            minute hour day month weekday — e.g. 0 9 * * 1-5 = weekdays at 9am
          </p>
        </div>
      )}

      {presetId !== "custom" && matchedPreset && (
        <p className="text-xs text-muted-foreground font-mono">
          {matchedPreset.cron}
        </p>
      )}
    </div>
  );
}
