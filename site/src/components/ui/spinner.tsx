import { cn } from "@/lib/utils"

/**
 * Indicator de incarcare discret, in cyan-ul brandului. Apare cu o mica
 * intarziere (delay-200): o incarcare rapida nu mai apuca sa clipeasca un spinner.
 */
function Spinner({ className, label = "Se încarcă…" }: { className?: string; label?: string }) {
  return (
    <span
      role="status"
      className={cn("inline-flex animate-in fade-in fill-mode-both delay-200 duration-300", className)}
    >
      <span className="h-7 w-7 animate-spin rounded-full border-2 border-brand-cyan/15 border-t-brand-cyan" />
      <span className="sr-only">{label}</span>
    </span>
  )
}

/** Bloc gri pulsand, pentru scheletele din loading.tsx. */
function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("animate-pulse rounded-xl bg-white/[0.05]", className)} />
}

export { Skeleton, Spinner }
