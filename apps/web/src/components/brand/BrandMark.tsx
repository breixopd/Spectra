import { Shield } from "lucide-react";

import { cn } from "@/lib/utils";

interface BrandMarkProps {
  size?: "sm" | "md" | "lg";
  showWordmark?: boolean;
  subtitle?: string;
  className?: string;
}

const sizeMap = {
  sm: { icon: "h-7 w-7", glyph: "h-3.5 w-3.5", title: "text-sm", sub: "text-2xs" },
  md: { icon: "h-9 w-9", glyph: "h-4 w-4", title: "text-base", sub: "text-xs" },
  lg: { icon: "h-11 w-11", glyph: "h-5 w-5", title: "text-lg", sub: "text-sm" },
} as const;

export function BrandMark({ size = "md", showWordmark = true, subtitle, className }: BrandMarkProps) {
  const s = sizeMap[size];

  return (
    <div className={cn("flex items-center gap-3", className)}>
      <span
        className={cn(
          "flex shrink-0 items-center justify-center rounded-lg border border-primary/25 bg-primary/10 text-primary shadow-[inset_0_1px_0_hsl(var(--primary)/0.15)]",
          s.icon,
        )}
      >
        <Shield className={s.glyph} strokeWidth={2.25} />
      </span>
      {showWordmark ? (
        <div className="min-w-0 leading-tight">
          <p className={cn("font-semibold tracking-tight text-foreground", s.title)}>Spectra</p>
          {subtitle ? (
            <p className={cn("truncate uppercase tracking-[0.2em] text-muted-foreground", s.sub)}>{subtitle}</p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
