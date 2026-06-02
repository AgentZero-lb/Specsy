import * as React from "react";
import { cn } from "@/lib/utils";

export const Input = React.forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement>
>(({ className, ...props }, ref) => (
  <input
    ref={ref}
    className={cn(
      "h-10 w-full rounded-btn border border-hairline bg-base px-3 text-sm text-foreground transition-colors placeholder:text-faint focus-visible:border-accent focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent",
      className,
    )}
    {...props}
  />
));
Input.displayName = "Input";
