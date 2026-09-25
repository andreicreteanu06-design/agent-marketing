import type * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

/** Eticheta de stare ("Conectat", "Nerentabil") in stilul shadcn/ui, pe tema site-ului. */
const badgeVariants = cva(
  "inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium whitespace-nowrap",
  {
    variants: {
      variant: {
        neutral: "border-border-subtle bg-background text-foreground-muted",
        success: "border-emerald-400/30 bg-emerald-400/10 text-emerald-300",
        warning: "border-amber-400/30 bg-amber-400/10 text-amber-200",
        danger: "border-red-400/30 bg-red-400/10 text-red-300",
      },
    },
    defaultVariants: {
      variant: "neutral",
    },
  }
)

const DOT: Record<NonNullable<VariantProps<typeof badgeVariants>["variant"]>, string> = {
  neutral: "bg-foreground-muted/60",
  success: "bg-emerald-400",
  warning: "bg-amber-400",
  danger: "bg-red-400",
}

function Badge({
  className,
  variant = "neutral",
  children,
  ...props
}: React.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return (
    <span data-slot="badge" className={cn(badgeVariants({ variant }), className)} {...props}>
      <span aria-hidden className={cn("h-1.5 w-1.5 rounded-full", DOT[variant ?? "neutral"])} />
      {children}
    </span>
  )
}

export { Badge, badgeVariants }
