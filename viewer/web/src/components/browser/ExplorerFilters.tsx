import { useEffect, useMemo, useRef, useState, type JSX } from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown } from "lucide-react";

import type { CostFilter, RatingFilter, RecordSummary, TimeFilter } from "@/lib/types";
import { useViewer, useViewerDispatch } from "@/lib/viewer-context";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn, formatCategoryLabel } from "@/lib/utils";

const timeOptions: Array<{ value: TimeFilter; label: string }> = [
  { value: "any", label: "Any time" },
  { value: "24h", label: "Last 24h" },
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
  { value: "90d", label: "Last 90 days" },
];

const ratingOptions: Array<{ value: RatingFilter; label: string }> = [
  { value: "any", label: "Any rating" },
  { value: "5", label: "5 stars" },
  { value: "4", label: "4 stars" },
  { value: "3", label: "3 stars" },
  { value: "2", label: "2 stars" },
  { value: "1", label: "1 star" },
  { value: "unrated", label: "Unrated" },
];

function uniqueRecords(records: Array<RecordSummary | null>): RecordSummary[] {
  const seen = new Map<string, RecordSummary>();

  for (const record of records) {
    if (!record) continue;
    if (!seen.has(record.record_id)) {
      seen.set(record.record_id, record);
    }
  }

  return Array.from(seen.values());
}

type CategoryOption = {
  value: string;
  label: string;
};

type CostBounds = {
  min: number;
  max: number;
};

const costFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 3,
});

const COST_FILTER_EPSILON = 0.0005;

function categoryTriggerLabel(options: CategoryOption[], selectedValues: string[]): string {
  if (selectedValues.length === 0) {
    return "All categories";
  }
  if (selectedValues.length === 1) {
    return options.find((option) => option.value === selectedValues[0])?.label ?? selectedValues[0];
  }
  return `${selectedValues.length} categories`;
}

function filterTriggerClass(active: boolean, className?: string): string {
  return cn(
    "h-7 w-auto min-w-0 rounded-full px-2.5 text-[10px]",
    active
      ? "border-[var(--accent)] bg-[var(--accent-soft)] text-[var(--accent)] hover:border-[var(--accent)] hover:bg-[var(--accent-hover)] focus-visible:border-[var(--accent)] data-[placeholder]:text-[var(--accent)]/80 [&_svg]:text-[var(--accent)]"
      : "border-[var(--border-default)] bg-[var(--surface-1)] text-[var(--text-primary)]",
    className,
  );
}

function CategoryMultiSelect({
  options,
  selectedValues,
  onChange,
}: {
  options: CategoryOption[];
  selectedValues: string[];
  onChange: (nextValues: string[]) => void;
}): JSX.Element {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const hasActiveFilter = selectedValues.length > 0;

  useEffect(() => {
    if (!open) {
      return;
    }

    const handlePointerDown = (event: MouseEvent) => {
      if (!containerRef.current) {
        return;
      }
      if (event.target instanceof Node && !containerRef.current.contains(event.target)) {
        setOpen(false);
      }
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
      }
    };

    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  const selectedSet = useMemo(() => new Set(selectedValues), [selectedValues]);
  const triggerLabel = categoryTriggerLabel(options, selectedValues);

  const toggleValue = (value: string) => {
    if (selectedSet.has(value)) {
      onChange(selectedValues.filter((item) => item !== value));
      return;
    }

    onChange([...selectedValues, value]);
  };

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        aria-expanded={open}
        aria-haspopup="listbox"
        onClick={() => setOpen((current) => !current)}
        className={cn(
          "flex max-w-[14rem] items-center justify-between gap-2 border outline-none transition-all duration-150 hover:border-[var(--border-strong)] focus-visible:ring-2 focus-visible:ring-[var(--accent-soft)]",
          filterTriggerClass(hasActiveFilter),
          !hasActiveFilter && "focus-visible:border-[var(--accent)]",
        )}
      >
        <span className="truncate">{triggerLabel}</span>
        <ChevronDown
          className={cn(
            "size-3 transition-transform duration-150",
            hasActiveFilter ? "text-[var(--accent)]" : "text-[var(--text-tertiary)]",
            open && "rotate-180",
          )}
        />
      </button>

      {open ? (
        <div className="absolute left-0 top-[calc(100%+0.375rem)] z-50 w-64 rounded-lg border border-[var(--border-default)] bg-[var(--surface-0)] p-1 shadow-[0_4px_16px_rgba(0,0,0,0.08),0_0_0_1px_rgba(0,0,0,0.02)]">
          <div className="flex items-center justify-between px-2 py-1">
            <span className="text-[10px] font-medium uppercase tracking-[0.04em] text-[var(--text-tertiary)]">Categories</span>
            {selectedValues.length > 0 ? (
              <button
                type="button"
                onClick={() => onChange([])}
                className="text-[10px] text-[var(--text-tertiary)] transition-colors hover:text-[var(--text-secondary)]"
              >
                Clear
              </button>
            ) : null}
          </div>

          <div role="listbox" aria-multiselectable="true" className="max-h-64 overflow-y-auto">
            {options.map((option) => {
              const selected = selectedSet.has(option.value);
              return (
                <button
                  key={option.value}
                  type="button"
                  role="option"
                  aria-selected={selected}
                  onClick={() => toggleValue(option.value)}
                  className="flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-[12px] text-[var(--text-primary)] outline-none transition-colors hover:bg-[var(--accent-soft)] focus-visible:bg-[var(--accent-soft)]"
                >
                  <span
                    className={cn(
                      "flex size-3.5 shrink-0 items-center justify-center rounded-sm border",
                      selected
                        ? "border-[var(--accent)] bg-[var(--accent-soft)] text-[var(--accent)]"
                        : "border-[var(--border-default)] bg-[var(--surface-1)] text-transparent",
                    )}
                  >
                    <Check className="size-3" />
                  </span>
                  <span className="truncate">{option.label}</span>
                </button>
              );
            })}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function formatCostValue(value: number): string {
  return costFormatter.format(value);
}

function getCostBounds(records: RecordSummary[], selectedRunId: string | null): CostBounds | null {
  const costs = records
    .filter((record) => !selectedRunId || record.run_id === selectedRunId)
    .map((record) => record.total_cost_usd)
    .filter((value): value is number => Number.isFinite(value));

  if (costs.length === 0) {
    return null;
  }

  return {
    min: Math.min(...costs),
    max: Math.max(...costs),
  };
}

function sameCostFilter(left: CostFilter, right: CostFilter): boolean {
  return left.min === right.min && left.max === right.max;
}

function normalizeCostFilterForBounds(costFilter: CostFilter, bounds: CostBounds): CostFilter {
  const clampedMin = costFilter.min == null ? null : Math.min(Math.max(costFilter.min, bounds.min), bounds.max);
  const clampedMax = costFilter.max == null ? null : Math.max(bounds.min, Math.min(costFilter.max, bounds.max));

  const normalized =
    clampedMin != null && clampedMax != null && clampedMin > clampedMax
      ? { min: clampedMax, max: clampedMin }
      : { min: clampedMin, max: clampedMax };

  return {
    min:
      normalized.min != null && normalized.min <= bounds.min + COST_FILTER_EPSILON
        ? null
        : normalized.min,
    max:
      normalized.max != null && normalized.max >= bounds.max - COST_FILTER_EPSILON
        ? null
        : normalized.max,
  };
}

function buildCostFilterFromSlider(values: number[], bounds: CostBounds): CostFilter {
  const [nextMin = bounds.min, nextMax = bounds.max] = values;
  return normalizeCostFilterForBounds({ min: nextMin, max: nextMax }, bounds);
}

function costTriggerLabel(bounds: CostBounds | null, costFilter: CostFilter): string {
  if (!bounds) {
    return "No cost data";
  }

  const min = costFilter.min ?? bounds.min;
  const max = costFilter.max ?? bounds.max;
  if (costFilter.min == null && costFilter.max == null) {
    return "Any cost";
  }

  return `${formatCostValue(min)} to ${formatCostValue(max)}`;
}

function CostRangeFilter({
  bounds,
  costFilter,
  onChange,
}: {
  bounds: CostBounds | null;
  costFilter: CostFilter;
  onChange: (nextValue: CostFilter) => void;
}): JSX.Element {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const [popoverPosition, setPopoverPosition] = useState<{ top: number; left: number; width: number } | null>(null);
  const sliderValue = useMemo(() => {
    if (!bounds) {
      return [0, 0];
    }

    return [costFilter.min ?? bounds.min, costFilter.max ?? bounds.max];
  }, [bounds, costFilter.max, costFilter.min]);

  const hasActiveFilter = costFilter.min != null || costFilter.max != null;
  const disabled = !bounds || Math.abs(bounds.max - bounds.min) <= COST_FILTER_EPSILON;
  const step = bounds && bounds.max - bounds.min > 0.5 ? 0.01 : 0.001;

  useEffect(() => {
    if (!open || !triggerRef.current) {
      return;
    }

    const updatePosition = () => {
      if (!triggerRef.current) {
        return;
      }
      const rect = triggerRef.current.getBoundingClientRect();
      setPopoverPosition({
        top: rect.bottom + 6,
        left: rect.left,
        width: Math.max(rect.width, 288),
      });
    };

    updatePosition();
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [open]);

  useEffect(() => {
    if (!open) {
      return;
    }

    const handlePointerDown = (event: MouseEvent) => {
      if (!containerRef.current) {
        return;
      }
      if (event.target instanceof Node && !containerRef.current.contains(event.target)) {
        setOpen(false);
      }
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
      }
    };

    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  return (
    <div ref={containerRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        aria-expanded={open}
        aria-haspopup="dialog"
        disabled={!bounds}
        onClick={() => {
          if (!bounds) {
            return;
          }
          setOpen((current) => !current);
        }}
        className={cn(
          "flex max-w-[16rem] items-center justify-between gap-2 border outline-none transition-all duration-150",
          filterTriggerClass(hasActiveFilter),
          bounds
            ? "focus-visible:ring-2 focus-visible:ring-[var(--accent-soft)]"
            : "cursor-not-allowed opacity-60",
          !hasActiveFilter && bounds && "hover:border-[var(--border-strong)] focus-visible:border-[var(--accent)]",
        )}
      >
        <span className="truncate">{costTriggerLabel(bounds, costFilter)}</span>
        <ChevronDown
          className={cn(
            "size-3 transition-transform duration-150",
            hasActiveFilter ? "text-[var(--accent)]" : "text-[var(--text-tertiary)]",
            open && "rotate-180",
          )}
        />
      </button>

      {open && bounds && popoverPosition
        ? createPortal(
            <div
              className="fixed z-[120] rounded-lg border border-[var(--border-default)] bg-[var(--surface-0)] p-1 shadow-[0_4px_16px_rgba(0,0,0,0.08),0_0_0_1px_rgba(0,0,0,0.02)]"
              style={{
                top: popoverPosition.top,
                left: popoverPosition.left,
                width: popoverPosition.width,
              }}
            >
              <div className="flex items-center justify-between px-2 py-1">
                <span className="text-[10px] font-medium uppercase tracking-[0.04em] text-[var(--text-tertiary)]">Cost range</span>
                {hasActiveFilter ? (
                  <button
                    type="button"
                    onClick={() => onChange({ min: null, max: null })}
                    className="text-[10px] text-[var(--text-tertiary)] transition-colors hover:text-[var(--text-secondary)]"
                  >
                    Clear
                  </button>
                ) : null}
              </div>

              <div className="space-y-2 px-2.5 py-2">
                <div className="font-mono text-[10px] text-[var(--text-secondary)]">
                  {hasActiveFilter ? costTriggerLabel(bounds, costFilter) : "Any cost"}
                </div>

                <Slider
                  min={bounds.min}
                  max={bounds.max}
                  step={step}
                  minStepsBetweenThumbs={0}
                  value={sliderValue}
                  disabled={disabled}
                  onValueChange={(values) => {
                    if (values.length !== 2) {
                      return;
                    }
                    onChange(buildCostFilterFromSlider(values, bounds));
                  }}
                />

                <div className="flex items-center justify-between font-mono text-[10px] text-[var(--text-quaternary)]">
                  <span>{formatCostValue(bounds.min)}</span>
                  <span>{formatCostValue(bounds.max)}</span>
                </div>
              </div>
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}

export function ExplorerFilters(): JSX.Element | null {
  const { bootstrap, sourceFilter, timeFilter, modelFilter, categoryFilters, costFilter, ratingFilter, selectedRunId } =
    useViewer();
  const dispatch = useViewerDispatch();

  const sourceRecords = useMemo(() => {
    if (!bootstrap) return [];

    return uniqueRecords(
      sourceFilter === "dataset"
        ? bootstrap.dataset_entries.map((entry) => entry.record)
        : bootstrap.workbench_entries.map((entry) => entry.record),
    );
  }, [bootstrap, sourceFilter]);

  const availableModels = useMemo(() => {
    return Array.from(
      new Set(sourceRecords.map((record) => record.model_id).filter((value): value is string => Boolean(value))),
    ).sort((left, right) => left.localeCompare(right));
  }, [sourceRecords]);

  const availableCostBounds = useMemo(
    () => getCostBounds(sourceRecords, selectedRunId),
    [selectedRunId, sourceRecords],
  );

  const costFilterActive = costFilter.min != null || costFilter.max != null;
  const timeFilterActive = timeFilter !== "any";
  const ratingFilterActive = ratingFilter !== "any";
  const modelFilterActive = modelFilter !== null;
  const categoryFilterActive = sourceFilter === "dataset" && categoryFilters.length > 0;

  const availableCategories = useMemo(() => {
    if (!bootstrap) return [];

    return Array.from(
      new Set(
        bootstrap.dataset_entries
          .map((entry) => entry.category_slug.trim())
          .filter((value) => value.length > 0),
      ),
    )
      .map((value) => ({ value, label: formatCategoryLabel(value) }))
      .sort((left, right) => left.label.localeCompare(right.label));
  }, [bootstrap]);

  useEffect(() => {
    if (!availableCostBounds) {
      if (costFilter.min != null || costFilter.max != null) {
        dispatch({ type: "SET_COST_FILTER", payload: { min: null, max: null } });
      }
      return;
    }

    const normalizedCostFilter = normalizeCostFilterForBounds(costFilter, availableCostBounds);
    if (!sameCostFilter(costFilter, normalizedCostFilter)) {
      dispatch({ type: "SET_COST_FILTER", payload: normalizedCostFilter });
    }
  }, [availableCostBounds, costFilter, dispatch]);

  if (!bootstrap) return null;

  const filtersActive =
    timeFilterActive ||
    costFilterActive ||
    ratingFilterActive ||
    modelFilterActive ||
    categoryFilterActive;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-medium uppercase tracking-[0.04em] text-[var(--text-tertiary)]">Filters</span>
        {filtersActive ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => {
              dispatch({ type: "SET_TIME_FILTER", payload: "any" });
              dispatch({ type: "SET_COST_FILTER", payload: { min: null, max: null } });
              dispatch({ type: "SET_RATING_FILTER", payload: "any" });
              dispatch({ type: "SET_MODEL_FILTER", payload: null });
              dispatch({ type: "SET_CATEGORY_FILTERS", payload: [] });
            }}
            className="h-5 px-1.5 text-[10px] text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
          >
            Clear
          </Button>
        ) : null}
      </div>

      <div className="flex flex-wrap gap-1.5">
        <Select value={timeFilter} onValueChange={(value) => dispatch({ type: "SET_TIME_FILTER", payload: value as TimeFilter })}>
          <SelectTrigger size="sm" className={filterTriggerClass(timeFilterActive)}>
            <SelectValue placeholder="Any time" />
          </SelectTrigger>
          <SelectContent>
            {timeOptions.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <CostRangeFilter
          bounds={availableCostBounds}
          costFilter={costFilter}
          onChange={(nextValue) => dispatch({ type: "SET_COST_FILTER", payload: nextValue })}
        />

        <Select value={ratingFilter} onValueChange={(value) => dispatch({ type: "SET_RATING_FILTER", payload: value as RatingFilter })}>
          <SelectTrigger size="sm" className={filterTriggerClass(ratingFilterActive)}>
            <SelectValue placeholder="Any rating" />
          </SelectTrigger>
          <SelectContent>
            {ratingOptions.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select
          value={modelFilter ?? "all"}
          onValueChange={(value) =>
            dispatch({
              type: "SET_MODEL_FILTER",
              payload: value === "all" ? null : value,
            })
          }
        >
          <SelectTrigger size="sm" className={filterTriggerClass(modelFilterActive, "max-w-full")}>
            <SelectValue placeholder="All models" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All models</SelectItem>
            {availableModels.map((model) => (
              <SelectItem key={model} value={model}>
                <span className="truncate font-mono text-[11px]">{model}</span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {sourceFilter === "dataset" && availableCategories.length > 0 ? (
          <CategoryMultiSelect
            options={availableCategories}
            selectedValues={categoryFilters}
            onChange={(nextValues) => dispatch({ type: "SET_CATEGORY_FILTERS", payload: nextValues })}
          />
        ) : null}
      </div>
    </div>
  );
}
