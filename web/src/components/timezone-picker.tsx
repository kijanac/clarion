import { useState } from "react";
import { ChevronsUpDownIcon, CheckIcon } from "lucide-react";
import { getTimeZones } from "@vvo/tzdb";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";

const TIMEZONES = getTimeZones({ includeUtc: true }).map((tz) => ({
  value: tz.name,
  label: `${tz.abbreviation} — ${tz.mainCities.join(", ") || tz.name}`,
  offset: tz.currentTimeFormat.split(" ")[0] ?? "",
}));

interface TimezonePickerProps {
  value: string;
  onChange: (value: string) => void;
}

export function TimezonePicker({ value, onChange }: TimezonePickerProps) {
  const [open, setOpen] = useState(false);
  const selected = TIMEZONES.find((tz) => tz.value === value);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <Button
            variant="outline"
            role="combobox"
            aria-expanded={open}
            className="w-full justify-between font-normal"
          />
        }
      >
        {selected ? selected.label : "Select timezone..."}
        <ChevronsUpDownIcon className="ml-2 size-4 shrink-0 opacity-50" />
      </PopoverTrigger>
      <PopoverContent className="w-[400px] p-0" align="start">
        <Command>
          <CommandInput placeholder="Search timezone..." />
          <CommandList>
            <CommandEmpty>No timezone found.</CommandEmpty>
            <CommandGroup>
              {TIMEZONES.map((tz) => (
                <CommandItem
                  key={tz.value}
                  value={`${tz.value} ${tz.label}`}
                  onSelect={() => {
                    onChange(tz.value);
                    setOpen(false);
                  }}
                >
                  <CheckIcon
                    className={cn(
                      "mr-2 size-4",
                      value === tz.value ? "opacity-100" : "opacity-0"
                    )}
                  />
                  <span className="text-xs text-muted-foreground w-16 shrink-0">
                    {tz.offset}
                  </span>
                  <span className="truncate">{tz.label}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
