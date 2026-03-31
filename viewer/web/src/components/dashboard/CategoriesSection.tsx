import { useCallback, useState, useMemo, type JSX } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronDown, ChevronRight, Download, Search } from "lucide-react";

import { formatCost } from "@/lib/dashboard-stats";
import { formatCategoryLabel, cn } from "@/lib/utils";
import type { DatasetEntry, SupercategoryOption, TimeFilter } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  pillClass,
  TIME_DURATIONS,
  STAR_SLIDER_MIN,
  STAR_SLIDER_MAX,
  type CostBounds,
  DashboardTimeFilter,
  DashboardStarsFilter,
  DashboardCostFilter,
} from "@/components/dashboard/dashboard-filters";

type CategoryStats = {
  count: number;
  sdk_package: string | null;
  average_rating: number | null;
  average_cost_usd: number | null;
};

type CategoriesSectionProps = {
  categoryStats: Record<string, CategoryStats>;
  supercategories?: SupercategoryOption[];
  datasetEntries?: DatasetEntry[];
};

type SortKey = "category" | "sdk_package" | "count" | "average_rating" | "average_cost_usd";
type SortDirection = "asc" | "desc";

function formatAverageRating(value: number | null): string {
  return value != null ? `${value.toFixed(1)}★` : "—";
}

function formatSdkPackage(value: string | null): string {
  if (value === "sdk_hybrid") return "sdk_hybrid";
  if (value === "sdk") return "sdk";
  return "—";
}

type CategoryRow = [string, CategoryStats];

function sortRows(rows: CategoryRow[], sortKey: SortKey, sortDirection: SortDirection): CategoryRow[] {
  return [...rows].sort((left, right) => {
    const [leftCategory, leftStats] = left;
    const [rightCategory, rightStats] = right;
    const leftCategoryLabel = formatCategoryLabel(leftCategory);
    const rightCategoryLabel = formatCategoryLabel(rightCategory);

    const categoryFallback = leftCategoryLabel.localeCompare(rightCategoryLabel);

    if (sortKey === "category") {
      return sortDirection === "asc" ? categoryFallback : -categoryFallback;
    }

    if (sortKey === "sdk_package") {
      const leftValue = formatSdkPackage(leftStats.sdk_package);
      const rightValue = formatSdkPackage(rightStats.sdk_package);
      const sdkDelta = leftValue.localeCompare(rightValue);
      if (sdkDelta === 0) return categoryFallback;
      return sortDirection === "asc" ? sdkDelta : -sdkDelta;
    }

    const leftValue = leftStats[sortKey];
    const rightValue = rightStats[sortKey];

    if (leftValue == null && rightValue == null) return categoryFallback;
    if (leftValue == null) return 1;
    if (rightValue == null) return -1;

    const numericDelta = leftValue - rightValue;
    if (numericDelta === 0) return categoryFallback;
    return sortDirection === "asc" ? numericDelta : -numericDelta;
  });
}

type SupercategoryGroup = {
  slug: string;
  title: string;
  rows: CategoryRow[];
  totalCount: number;
  avgRating: number | null;
  avgCost: number | null;
};

function buildGroups(
  rows: CategoryRow[],
  supercategories: SupercategoryOption[],
): SupercategoryGroup[] {
  const catToSuper = new Map<string, string>();
  const superBySlug = new Map<string, SupercategoryOption>();
  for (const sc of supercategories) {
    superBySlug.set(sc.slug, sc);
    for (const cat of sc.category_slugs) {
      catToSuper.set(cat, sc.slug);
    }
  }

  const grouped = new Map<string, CategoryRow[]>();
  for (const sc of supercategories) {
    grouped.set(sc.slug, []);
  }
  grouped.set("__uncategorized__", []);

  for (const row of rows) {
    const superSlug = catToSuper.get(row[0]);
    const key = superSlug ?? "__uncategorized__";
    grouped.get(key)!.push(row);
  }

  const groups: SupercategoryGroup[] = [];
  for (const sc of supercategories) {
    const scRows = grouped.get(sc.slug) ?? [];
    if (scRows.length === 0) continue;
    groups.push(buildGroupStats(sc.slug, sc.title, scRows));
  }
  const uncategorized = grouped.get("__uncategorized__") ?? [];
  if (uncategorized.length > 0) {
    groups.push(buildGroupStats("__uncategorized__", "Uncategorized", uncategorized));
  }
  return groups;
}

function buildGroupStats(slug: string, title: string, rows: CategoryRow[]): SupercategoryGroup {
  let totalCount = 0;
  let ratingSum = 0;
  let ratingCount = 0;
  let costSum = 0;
  let costCount = 0;
  for (const [, stats] of rows) {
    totalCount += stats.count;
    if (stats.average_rating != null) {
      ratingSum += stats.average_rating * stats.count;
      ratingCount += stats.count;
    }
    if (stats.average_cost_usd != null) {
      costSum += stats.average_cost_usd * stats.count;
      costCount += stats.count;
    }
  }
  return {
    slug,
    title,
    rows,
    totalCount,
    avgRating: ratingCount > 0 ? Math.round((ratingSum / ratingCount) * 10) / 10 : null,
    avgCost: costCount > 0 ? Math.round((costSum / costCount) * 10000) / 10000 : null,
  };
}

function CategoryTableRows({
  rows,
  startIndex,
}: {
  rows: CategoryRow[];
  startIndex: number;
}): JSX.Element {
  return (
    <>
      {rows.map(([category, stats], index) => (
        <TableRow
          key={category}
          className="border-b border-[var(--border-subtle)] hover:bg-[var(--surface-1)]"
        >
          <TableCell className="w-8 px-0 py-[5px] text-center font-mono tabular-nums text-[var(--text-quaternary)]">
            {startIndex + index + 1}
          </TableCell>
          <TableCell className="w-full px-4 py-[5px] text-[var(--text-secondary)]">
            {formatCategoryLabel(category)}
          </TableCell>
          <TableCell className="whitespace-nowrap px-4 py-[5px] text-[var(--text-tertiary)]">
            {stats.sdk_package ? (
              <Badge variant="secondary" className="rounded-sm px-1.5 py-0 font-mono text-[10px]">
                {formatSdkPackage(stats.sdk_package)}
              </Badge>
            ) : (
              <span className="font-mono text-[var(--text-quaternary)]">—</span>
            )}
          </TableCell>
          <TableCell className="whitespace-nowrap px-4 py-[5px] text-right font-mono tabular-nums text-[var(--text-tertiary)]">
            {stats.count}
          </TableCell>
          <TableCell className="whitespace-nowrap px-4 py-[5px] text-right font-mono tabular-nums text-[var(--text-tertiary)]">
            {formatAverageRating(stats.average_rating)}
          </TableCell>
          <TableCell className="whitespace-nowrap px-4 py-[5px] text-right font-mono tabular-nums text-[var(--text-tertiary)]">
            {formatCost(stats.average_cost_usd)}
          </TableCell>
        </TableRow>
      ))}
    </>
  );
}

export function CategoriesSection({ categoryStats, supercategories, datasetEntries }: CategoriesSectionProps): JSX.Element | null {
  const [filter, setFilter] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("count");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());

  // --- local filter state ---
  const [timeFilter, setTimeFilter] = useState<TimeFilter>({ oldest: null, newest: null });
  const [starsFilter, setStarsFilter] = useState<[number, number]>([STAR_SLIDER_MIN, STAR_SLIDER_MAX]);
  const [costFilter, setCostFilter] = useState<{ min: number | null; max: number | null }>({ min: null, max: null });
  const [sdkFilter, setSdkFilter] = useState<string | null>(null);

  const timeFilterActive = timeFilter.oldest != null || timeFilter.newest != null;
  const starsFilterActive = starsFilter[0] !== STAR_SLIDER_MIN || starsFilter[1] !== STAR_SLIDER_MAX;
  const costFilterActive = costFilter.min != null || costFilter.max != null;
  const sdkFilterActive = sdkFilter !== null;
  const anyFilterActive = timeFilterActive || starsFilterActive || costFilterActive || sdkFilterActive;

  // Compute which categories pass the time filter using dataset_entries
  const timeSlugs = useMemo<Set<string> | null>(() => {
    if (!timeFilterActive || !datasetEntries) return null;
    const now = Date.now();
    const maxAge = timeFilter.oldest ? TIME_DURATIONS[timeFilter.oldest] : null;
    const minAge = timeFilter.newest ? TIME_DURATIONS[timeFilter.newest] : null;
    const slugs = new Set<string>();
    for (const entry of datasetEntries) {
      const ts = entry.record?.created_at ? new Date(entry.record.created_at).getTime() : 0;
      if (!ts) continue;
      const age = now - ts;
      if (maxAge != null && age > maxAge) continue;
      if (minAge != null && age < minAge) continue;
      slugs.add(entry.category_slug);
    }
    return slugs;
  }, [timeFilterActive, timeFilter, datasetEntries]);

  // Available SDK values from category stats
  const availableSdks = useMemo(() => {
    return Array.from(
      new Set(
        Object.values(categoryStats)
          .map((s) => s.sdk_package)
          .filter((v): v is string => Boolean(v)),
      ),
    ).sort((a, b) => a.localeCompare(b));
  }, [categoryStats]);

  // Cost bounds across all categories
  const categoryCostBounds = useMemo<CostBounds | null>(() => {
    const costs = Object.values(categoryStats)
      .map((s) => s.average_cost_usd)
      .filter((v): v is number => v != null && Number.isFinite(v));
    if (costs.length === 0) return null;
    return { min: Math.min(...costs), max: Math.max(...costs) };
  }, [categoryStats]);

  // Apply dimension filters to category stats
  const filteredCategoryStats = useMemo(() => {
    const result: Record<string, CategoryStats> = {};
    for (const [slug, stats] of Object.entries(categoryStats)) {
      if (timeSlugs && !timeSlugs.has(slug)) continue;
      if (sdkFilter && stats.sdk_package !== sdkFilter) continue;
      if (starsFilterActive) {
        if (stats.average_rating == null) continue;
        if (stats.average_rating < starsFilter[0] || stats.average_rating > starsFilter[1]) continue;
      }
      if (costFilterActive) {
        if (stats.average_cost_usd == null) continue;
        if (costFilter.min != null && stats.average_cost_usd < costFilter.min) continue;
        if (costFilter.max != null && stats.average_cost_usd > costFilter.max) continue;
      }
      result[slug] = stats;
    }
    return result;
  }, [categoryStats, timeSlugs, sdkFilter, starsFilter, starsFilterActive, costFilter, costFilterActive]);

  const allEntries = useMemo(
    () => Object.entries(filteredCategoryStats) as CategoryRow[],
    [filteredCategoryStats],
  );

  const allSorted = useMemo(
    () => sortRows(allEntries, sortKey, sortDirection),
    [allEntries, sortKey, sortDirection],
  );

  const exportCsv = useCallback(
    (rows: CategoryRow[]) => {
      const header = "Category,SDK,Count,Avg Stars,Avg Cost USD";
      const lines = rows.map(([slug, s]) => {
        const cat = formatCategoryLabel(slug).replaceAll('"', '""');
        const sdk = formatSdkPackage(s.sdk_package);
        const rating = s.average_rating != null ? s.average_rating.toFixed(1) : "";
        const cost = s.average_cost_usd != null ? s.average_cost_usd.toFixed(4) : "";
        return `"${cat}",${sdk},${s.count},${rating},${cost}`;
      });
      const blob = new Blob([header + "\n" + lines.join("\n") + "\n"], { type: "text/csv" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "categories.csv";
      a.click();
      URL.revokeObjectURL(url);
    },
    [],
  );

  const filtered = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    return needle
      ? allSorted.filter(([category]) => formatCategoryLabel(category).toLowerCase().includes(needle))
      : allSorted;
  }, [allSorted, filter]);

  const hasSupercategories = supercategories && supercategories.length > 0;

  const groups = useMemo(() => {
    if (!hasSupercategories) return null;
    return buildGroups(
      sortRows(
        filtered.map(([cat, stats]) => [cat, stats]),
        sortKey,
        sortDirection,
      ),
      supercategories,
    );
  }, [filtered, hasSupercategories, supercategories, sortKey, sortDirection]);

  // Total unfiltered count for the header counter
  const unfilteredCount = Object.keys(categoryStats).length;

  if (unfilteredCount === 0) return null;

  function toggleSort(nextSortKey: SortKey): void {
    if (nextSortKey === sortKey) {
      setSortDirection((current) => (current === "asc" ? "desc" : "asc"));
      return;
    }
    setSortKey(nextSortKey);
    setSortDirection(nextSortKey === "category" || nextSortKey === "sdk_package" ? "asc" : "desc");
  }

  function toggleGroup(slug: string): void {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(slug)) {
        next.delete(slug);
      } else {
        next.add(slug);
      }
      return next;
    });
  }

  function SortIndicator({ column }: { column: SortKey }): JSX.Element {
    if (sortKey !== column) {
      return <ArrowUpDown className="size-3 text-[var(--text-quaternary)]" />;
    }
    if (sortDirection === "asc") {
      return <ArrowUp className="size-3 text-[var(--text-tertiary)]" />;
    }
    return <ArrowDown className="size-3 text-[var(--text-tertiary)]" />;
  }

  let runningIndex = 0;

  return (
    <section>
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-[10px] font-medium uppercase tracking-[0.06em] text-[var(--text-tertiary)]">
          Categories
        </h2>
        <div className="flex items-center gap-2">
          <span className="text-[10px] tabular-nums text-[var(--text-quaternary)]">
            {filtered.length === unfilteredCount
              ? `${unfilteredCount}`
              : `${filtered.length} / ${unfilteredCount}`}
          </span>
          <button
            type="button"
            onClick={() => exportCsv(filtered)}
            title="Export CSV"
            className="rounded p-0.5 text-[var(--text-quaternary)] transition-colors hover:bg-[var(--surface-1)] hover:text-[var(--text-tertiary)]"
          >
            <Download className="size-3" />
          </button>
        </div>
      </div>
      <div className="rounded-md border border-[var(--border-default)] bg-[var(--surface-0)]">
        {/* --- filter bar --- */}
        <div className="flex flex-wrap items-center gap-1.5 border-b border-[var(--border-default)] px-3 py-1.5">
          <DashboardStarsFilter value={starsFilter} onChange={setStarsFilter} />
          <DashboardTimeFilter value={timeFilter} onChange={setTimeFilter} />
          <DashboardCostFilter bounds={categoryCostBounds} value={costFilter} onChange={setCostFilter} />

          {availableSdks.length > 1 ? (
            <Select value={sdkFilter ?? "all"} onValueChange={(v) => setSdkFilter(v === "all" ? null : v)}>
              <SelectTrigger size="sm" className={cn(pillClass(sdkFilterActive), "h-6")}>
                <SelectValue placeholder="All SDKs" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All SDKs</SelectItem>
                {availableSdks.map((sdk) => (
                  <SelectItem key={sdk} value={sdk}>
                    <span className="truncate font-mono text-[10px]">{sdk}</span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : null}

          {anyFilterActive ? (
            <button
              type="button"
              onClick={() => {
                setTimeFilter({ oldest: null, newest: null });
                setStarsFilter([STAR_SLIDER_MIN, STAR_SLIDER_MAX]);
                setCostFilter({ min: null, max: null });
                setSdkFilter(null);
              }}
              className="h-6 px-2 text-[10px] text-[var(--text-tertiary)] transition-colors hover:text-[var(--text-secondary)]"
            >
              Clear all
            </button>
          ) : null}

          {/* spacer pushes search to the right */}
          <div className="flex-1" />

          {unfilteredCount > 12 ? (
            <div className="flex items-center gap-1.5">
              <Search className="size-3 shrink-0 text-[var(--text-quaternary)]" />
              <input
                type="text"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Filter categories..."
                className="h-6 w-36 bg-transparent text-[11px] text-[var(--text-primary)] placeholder:text-[var(--text-quaternary)] focus:outline-none"
              />
            </div>
          ) : null}
        </div>

        <div className="custom-scrollbar max-h-[320px] overflow-y-auto">
          {filtered.length === 0 ? (
            <div className="px-4 py-3">
              <span className="text-[11px] text-[var(--text-quaternary)]">No matching categories</span>
            </div>
          ) : (
            <Table className="text-[11px]">
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="h-8 w-8 px-0 py-[5px] text-center text-[10px] uppercase tracking-[0.06em] text-[var(--text-quaternary)]">
                    #
                  </TableHead>
                  <TableHead className="h-8 px-4 py-[5px] text-[10px] uppercase tracking-[0.06em] text-[var(--text-quaternary)]">
                    <button
                      type="button"
                      onClick={() => toggleSort("category")}
                      className="flex items-center gap-1 text-left"
                    >
                      <span>Category</span>
                      <SortIndicator column="category" />
                    </button>
                  </TableHead>
                  <TableHead className="h-8 whitespace-nowrap px-4 py-[5px] text-[10px] uppercase tracking-[0.06em] text-[var(--text-quaternary)]">
                    <button
                      type="button"
                      onClick={() => toggleSort("sdk_package")}
                      className="flex items-center gap-1 text-left"
                    >
                      <span>SDK</span>
                      <SortIndicator column="sdk_package" />
                    </button>
                  </TableHead>
                  <TableHead className="h-8 whitespace-nowrap px-4 py-[5px] text-right text-[10px] uppercase tracking-[0.06em] text-[var(--text-quaternary)]">
                    <button
                      type="button"
                      onClick={() => toggleSort("count")}
                      className="ml-auto flex items-center gap-1"
                    >
                      <span>Count</span>
                      <SortIndicator column="count" />
                    </button>
                  </TableHead>
                  <TableHead className="h-8 whitespace-nowrap px-4 py-[5px] text-right text-[10px] uppercase tracking-[0.06em] text-[var(--text-quaternary)]">
                    <button
                      type="button"
                      onClick={() => toggleSort("average_rating")}
                      className="ml-auto flex items-center gap-1"
                    >
                      <span>Avg Stars</span>
                      <SortIndicator column="average_rating" />
                    </button>
                  </TableHead>
                  <TableHead className="h-8 whitespace-nowrap px-4 py-[5px] text-right text-[10px] uppercase tracking-[0.06em] text-[var(--text-quaternary)]">
                    <button
                      type="button"
                      onClick={() => toggleSort("average_cost_usd")}
                      className="ml-auto flex items-center gap-1"
                    >
                      <span>Avg Cost</span>
                      <SortIndicator column="average_cost_usd" />
                    </button>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {groups
                  ? groups.map((group) => {
                      const collapsed = collapsedGroups.has(group.slug);
                      const groupStartIndex = runningIndex;
                      if (!collapsed) {
                        runningIndex += group.rows.length;
                      }
                      return (
                        <SupercategoryGroupRows
                          key={group.slug}
                          group={group}
                          collapsed={collapsed}
                          startIndex={groupStartIndex}
                          onToggle={() => toggleGroup(group.slug)}
                        />
                      );
                    })
                  : (
                    <CategoryTableRows rows={filtered} startIndex={0} />
                  )}
              </TableBody>
            </Table>
          )}
        </div>
      </div>
    </section>
  );
}

function SupercategoryGroupRows({
  group,
  collapsed,
  startIndex,
  onToggle,
}: {
  group: SupercategoryGroup;
  collapsed: boolean;
  startIndex: number;
  onToggle: () => void;
}): JSX.Element {
  return (
    <>
      <TableRow
        className="border-b border-[var(--border-default)] bg-[var(--surface-1)] hover:bg-[var(--surface-1)]"
      >
        <TableCell colSpan={3} className="px-2 py-[5px]">
          <button
            type="button"
            onClick={onToggle}
            className="flex items-center gap-1.5 text-left text-[11px] font-medium text-[var(--text-secondary)]"
          >
            {collapsed ? (
              <ChevronRight className="size-3 text-[var(--text-tertiary)]" />
            ) : (
              <ChevronDown className="size-3 text-[var(--text-tertiary)]" />
            )}
            <span>{group.title}</span>
            <span className="font-normal text-[var(--text-quaternary)]">
              ({group.rows.length})
            </span>
          </button>
        </TableCell>
        <TableCell className="whitespace-nowrap px-4 py-[5px] text-right font-mono tabular-nums text-[var(--text-tertiary)]">
          {group.totalCount}
        </TableCell>
        <TableCell className="whitespace-nowrap px-4 py-[5px] text-right font-mono tabular-nums text-[var(--text-tertiary)]">
          {formatAverageRating(group.avgRating)}
        </TableCell>
        <TableCell className="whitespace-nowrap px-4 py-[5px] text-right font-mono tabular-nums text-[var(--text-tertiary)]">
          {formatCost(group.avgCost)}
        </TableCell>
      </TableRow>
      {!collapsed ? (
        <CategoryTableRows rows={group.rows} startIndex={startIndex} />
      ) : null}
    </>
  );
}
