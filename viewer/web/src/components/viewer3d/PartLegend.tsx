import { type JSX } from "react";

import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

export type PartLegendItem = {
  name: string;
  color: string;
};

type PartLegendProps = {
  items: PartLegendItem[];
  selectedPartName: string | null;
  onSelectPart: (name: string | null) => void;
};

export function PartLegend({
  items,
  selectedPartName,
  onSelectPart,
}: PartLegendProps): JSX.Element | null {
  if (items.length === 0) {
    return null;
  }

  return (
    <div className="pointer-events-auto absolute right-3 top-3 z-20 w-[min(12.5rem,calc(100%-1.5rem))] overflow-hidden rounded-[18px] bg-[rgba(245,245,245,0.94)] p-1.5 shadow-[0_10px_28px_rgba(17,17,17,0.06)] backdrop-blur-xl">
      <ScrollArea className="max-h-[min(42vh,12rem)]">
        <div className="space-y-0.5">
          {items.map((item) => {
            const isSelected = item.name === selectedPartName;

            return (
              <button
                key={item.name}
                type="button"
                aria-pressed={isSelected}
                onClick={() => onSelectPart(isSelected ? null : item.name)}
                className={cn(
                  "group flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left transition-colors duration-150",
                  isSelected
                    ? "bg-white/[0.96] shadow-[inset_0_0_0_1px_rgba(12,140,233,0.14)]"
                    : "bg-transparent hover:bg-white/[0.7]",
                )}
              >
                <span
                  aria-hidden="true"
                  className="h-2 w-2 shrink-0 rounded-full"
                  style={{ backgroundColor: item.color }}
                />
                <span
                  className="min-w-0 flex-1 truncate font-mono text-[10px] text-[var(--text-primary)]"
                  title={item.name}
                >
                  {item.name}
                </span>
                <span
                  aria-hidden="true"
                  className={cn(
                    "h-1 w-1 shrink-0 rounded-full transition-opacity duration-150",
                    isSelected
                      ? "bg-[var(--accent)] opacity-100"
                      : "bg-[var(--border-strong)] opacity-0 group-hover:opacity-80",
                  )}
                />
              </button>
            );
          })}
        </div>
      </ScrollArea>
    </div>
  );
}
