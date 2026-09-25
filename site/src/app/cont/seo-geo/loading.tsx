import { Skeleton } from "@/components/ui/spinner";

/**
 * Scheletul zonei de continut din modulul SEO + GEO: meniul lateral (din
 * layout.tsx) ramane afisat si functional, se asteapta doar pagina.
 */
export default function Loading() {
  return (
    <div role="status" aria-label="Se încarcă…">
      <Skeleton className="h-8 w-56" />
      <Skeleton className="mt-3 h-4 w-full max-w-md" />
      <div className="mt-8 grid grid-cols-2 gap-4 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="rounded-3xl border border-border-subtle bg-background-elevated p-5">
            <Skeleton className="h-3 w-20" />
            <Skeleton className="mt-3 h-7 w-16" />
          </div>
        ))}
      </div>
      <div className="mt-6 rounded-3xl border border-border-subtle bg-background-elevated p-6">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="mt-6 h-64 w-full" />
      </div>
    </div>
  );
}
