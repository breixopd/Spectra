import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface KeyValueProps {
  label: string;
  value: ReactNode;
  mono?: boolean;
  className?: string;
}

export function KeyValue({ label, value, mono, className }: KeyValueProps) {
  return (
    <div className={cn("grid grid-cols-[minmax(0,8rem)_1fr] gap-x-3 gap-y-0.5 text-sm", className)}>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={cn("min-w-0 break-words", mono && "font-mono text-xs")}>{value}</dd>
    </div>
  );
}

interface RelativeTimeProps {
  date: string | null | undefined;
  className?: string;
}

export function RelativeTime({ date, className }: RelativeTimeProps) {
  if (!date) {
    return <span className={cn("text-muted-foreground", className)}>—</span>;
  }

  const parsed = new Date(date);
  if (Number.isNaN(parsed.getTime())) {
    return <span className={className}>{date}</span>;
  }

  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  const diffMs = parsed.getTime() - Date.now();
  const diffSec = Math.round(diffMs / 1000);
  const absSec = Math.abs(diffSec);

  let relative: string;
  if (absSec < 60) {
    relative = rtf.format(diffSec, "second");
  } else if (absSec < 3600) {
    relative = rtf.format(Math.round(diffSec / 60), "minute");
  } else if (absSec < 86400) {
    relative = rtf.format(Math.round(diffSec / 3600), "hour");
  } else {
    relative = rtf.format(Math.round(diffSec / 86400), "day");
  }

  return (
    <time dateTime={parsed.toISOString()} className={cn("tabular-nums", className)} title={parsed.toLocaleString()}>
      {relative}
    </time>
  );
}

interface ScoreChipProps {
  score: number | null | undefined;
  label?: string;
  className?: string;
}

export function ScoreChip({ score, label = "CVSS", className }: ScoreChipProps) {
  if (score === null || score === undefined) {
    return <span className={cn("text-xs text-muted-foreground", className)}>—</span>;
  }

  const tone =
    score >= 9 ? "text-critical" : score >= 7 ? "text-destructive" : score >= 4 ? "text-warning" : "text-muted-foreground";

  return (
    <span className={cn("inline-flex items-center gap-1 rounded-md border border-border bg-muted/40 px-2 py-0.5 font-mono text-xs", className)}>
      <span className="text-muted-foreground">{label}</span>
      <span className={cn("font-semibold tabular-nums", tone)}>{score.toFixed(1)}</span>
    </span>
  );
}

interface MoneyChipProps {
  amount: number | null | undefined;
  currency?: string;
  className?: string;
}

export function MoneyChip({ amount, currency = "USD", className }: MoneyChipProps) {
  if (amount === null || amount === undefined) {
    return <span className={cn("text-xs text-muted-foreground", className)}>—</span>;
  }

  const formatted = new Intl.NumberFormat(undefined, { style: "currency", currency, maximumFractionDigits: 0 }).format(amount);

  return (
    <span className={cn("inline-flex rounded-md border border-border bg-muted/40 px-2 py-0.5 font-mono text-xs tabular-nums", className)}>
      {formatted}
    </span>
  );
}
