import * as React from "react";
import { cn } from "@/lib/utils";

type Variant = "default" | "accent" | "success" | "warning" | "outline";

const variants: Record<Variant, string> = {
  default: "border-hairline bg-elevated text-muted",
  accent: "border-accent/30 bg-accent/10 text-accent-soft",
  success: "border-success/30 bg-success/10 text-success",
  warning: "border-warning/30 bg-warning/10 text-warning",
  outline: "border-hairline-strong bg-transparent text-muted",
};

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: Variant;
}

export function Badge({ className, variant = "default", ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium",
        variants[variant],
        className,
      )}
      {...props}
    />
  );
}
