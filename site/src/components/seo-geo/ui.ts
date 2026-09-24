/**
 * Stilurile de buton si formatarile comune modulului SEO + GEO.
 *
 * Butoanele sunt `Button` din shadcn/ui (components/ui/button.tsx) cu clasele
 * de aici peste varianta lui - aceleasi pilule albastre ca CTA-urile din restul
 * site-ului, nu butonul alb implicit al paletei shadcn.
 */

export const primaryButton =
  "h-9 rounded-full bg-brand-blue px-4 font-semibold text-white hover:bg-brand-blue/90";

export const outlineButton =
  "h-9 rounded-full border-border-subtle bg-transparent px-4 text-foreground hover:bg-white/[0.05]";

export const ghostButton =
  "h-9 rounded-full px-3 text-foreground-muted hover:bg-white/[0.05] hover:text-foreground";

/**
 * "1 pagină", "9 pagini", "20 de pagini" - regula romaneasca: de la 20 in sus
 * (si la sutele rotunde) numeralul cere "de".
 */
export function countLabel(count: number, singular: string, plural: string): string {
  if (count === 1) return `1 ${singular}`;
  const rest = count % 100;
  const needsDe = count > 0 && (rest === 0 || rest >= 20);
  return `${count} ${needsDe ? "de " : ""}${plural}`;
}

/** "24 sept." - data scurta, ca in rapoartele din interfata. */
export function shortDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString("ro-RO", { day: "numeric", month: "short" });
}

/** "24 sept., 20:30" - cand s-a terminat un audit. */
export function dateTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("ro-RO", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const NUMBER = new Intl.NumberFormat("ro-RO");
const PERCENT = new Intl.NumberFormat("ro-RO", { style: "percent", maximumFractionDigits: 1 });
const DECIMAL = new Intl.NumberFormat("ro-RO", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

/** O valoare de indicator, dupa felul ei: 4.306 / 59,9 % / 14,8. */
export function formatMetric(value: number | null, format: "number" | "percent" | "position"): string {
  if (value === null) return "—";
  if (format === "percent") return PERCENT.format(value);
  if (format === "position") return DECIMAL.format(value);
  return NUMBER.format(value);
}

export function formatDecimal(value: number): string {
  return DECIMAL.format(value);
}

/** "2026-09-21" -> Date locala, fara decalajul de fus orar al lui new Date(iso). */
export function parseDay(iso: string): Date {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(year, month - 1, day);
}

/** "21 sept." - pe axa graficului. */
export function axisDay(iso: string): string {
  return parseDay(iso).toLocaleDateString("ro-RO", { day: "numeric", month: "short" });
}

/** "duminică, 21 septembrie" - in tooltip-ul graficului. */
export function longDay(iso: string): string {
  return parseDay(iso).toLocaleDateString("ro-RO", {
    weekday: "long",
    day: "numeric",
    month: "long",
  });
}
