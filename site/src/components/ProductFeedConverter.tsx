"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  CheckCircle,
  DownloadSimple,
  FileArrowUp,
  Warning,
} from "@phosphor-icons/react/dist/ssr";
import { getToken } from "@/lib/auth";
import {
  autoMapColumns,
  convertRows,
  parseSourceFile,
  rowsToCsv,
  PRODUCT_FIELDS,
  type ChatGptProductRow,
  type Mapping,
  type ParsedSource,
  type ProductAvailability,
} from "@/lib/productFeed";
import { ResultReveal, RevealSection } from "./RevealSection";

type Step = "upload" | "map" | "done";

const CURRENCIES = ["RON", "EUR", "USD"];
const AVAILABILITY_OPTIONS: ProductAvailability[] = [
  "in_stock",
  "out_of_stock",
  "pre_order",
  "backorder",
  "unknown",
];

/**
 * Convertor catalog -> feed de produse in formatul ChatGPT Shopping (vezi
 * lib/productFeed.ts pentru sursa specificatiei). Acelasi tipar de protectie
 * ca SeoGeoDashboard/AccountDashboard: fara token, redirectioneaza spre
 * /login. Totul client-side - fisierul brut al clientului nu ajunge pe niciun
 * server (nici al nostru, nici al OpenAI - doar conversie + descarcare).
 */
export function ProductFeedConverter() {
  const router = useRouter();
  const [checkingAuth, setCheckingAuth] = useState(true);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [step, setStep] = useState<Step>("upload");
  const [fileName, setFileName] = useState("");
  const [source, setSource] = useState<ParsedSource | null>(null);
  const [mapping, setMapping] = useState<Mapping>({});
  const [currency, setCurrency] = useState("RON");
  const [defaultAvailability, setDefaultAvailability] = useState<ProductAvailability>("in_stock");
  const [fileError, setFileError] = useState<string | null>(null);

  const [convertedRows, setConvertedRows] = useState<ChatGptProductRow[]>([]);
  const [issues, setIssues] = useState<string[]>([]);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setCheckingAuth(false);
  }, [router]);

  async function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setFileError(null);
    try {
      const parsed = await parseSourceFile(file);
      setSource(parsed);
      setMapping(autoMapColumns(parsed.columns));
      setFileName(file.name);
      setStep("map");
    } catch (err) {
      setFileError(err instanceof Error ? err.message : "Fișierul nu a putut fi citit.");
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  function handleConvert() {
    if (!source) return;
    const result = convertRows(source.rows, mapping, { currency, defaultAvailability });
    setConvertedRows(result.rows);
    setIssues(result.issues);
    setStep("done");
  }

  function handleDownload() {
    const csv = rowsToCsv(convertedRows);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "produse-chatgpt.csv";
    a.click();
    URL.revokeObjectURL(url);
  }

  function handleReset() {
    setStep("upload");
    setSource(null);
    setMapping({});
    setConvertedRows([]);
    setIssues([]);
    setFileError(null);
  }

  if (checkingAuth) {
    return <p className="text-sm text-foreground-muted">Se încarcă...</p>;
  }

  return (
    <div className="space-y-8">
      <RevealSection className="rounded-3xl border border-border-subtle bg-background-elevated p-6 md:p-8">
        <div className="flex items-center gap-2">
          <FileArrowUp size={16} className="text-brand-cyan" />
          <h2 className="text-lg font-semibold text-foreground">1. Încarcă catalogul</h2>
        </div>
        <p className="mt-2 text-sm text-foreground-muted">
          Un export din magazinul tău (Shopify, WooCommerce, Excel sau orice
          altă sursă) - coloanele pot avea orice denumire, le potrivim la pasul
          următor.
        </p>
        <label className="mt-5 flex cursor-pointer items-center justify-center gap-2 rounded-full bg-brand-blue px-6 py-3.5 text-sm font-semibold text-white transition-transform hover:scale-[1.01] active:scale-[0.99]">
          <FileArrowUp size={16} weight="bold" />
          Alege fișier (.csv, .tsv, .xml, .xlsx, .xls, .ods)
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,.tsv,.xml,.xlsx,.xls,.ods"
            onChange={handleFileChange}
            className="hidden"
          />
        </label>
        {fileName && step !== "upload" && (
          <p className="mt-3 text-xs text-foreground-muted">Fișier curent: {fileName}</p>
        )}
        {fileError && (
          <p role="alert" className="mt-4 rounded-xl bg-red-500/10 px-4 py-3 text-sm text-red-400">
            {fileError}
          </p>
        )}
      </RevealSection>

      {(step === "map" || step === "done") && source && (
        <ResultReveal className="rounded-3xl border border-border-subtle bg-background-elevated p-6 md:p-8">
          <h2 className="text-lg font-semibold text-foreground">
            2. Potrivește coloanele ({source.rows.length} produse detectate)
          </h2>
          <p className="mt-2 text-sm text-foreground-muted">
            Am potrivit automat ce am recunoscut - verifică și corectează unde e
            nevoie. Câmpurile marcate cu <span className="text-red-400">*</span> sunt
            obligatorii în formatul ChatGPT.
          </p>

          <div className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-2">
            {PRODUCT_FIELDS.map((field) => (
              <div key={field.key} className="flex flex-col gap-1.5">
                <label className="text-sm font-medium text-foreground">
                  {field.label}
                  {field.required && <span className="text-red-400"> *</span>}
                  {field.hint && (
                    <span className="ml-1.5 text-xs font-normal text-foreground-muted">
                      ({field.hint})
                    </span>
                  )}
                </label>
                <select
                  value={mapping[field.key] ?? ""}
                  onChange={(e) =>
                    setMapping((prev) => ({
                      ...prev,
                      [field.key]: e.target.value || null,
                    }))
                  }
                  className="rounded-xl border border-border-subtle bg-background px-4 py-2.5 text-sm text-foreground outline-none transition-colors focus:border-brand-cyan"
                >
                  <option value="">— nemapat —</option>
                  {source.columns.map((column) => (
                    <option key={column} value={column}>
                      {column}
                    </option>
                  ))}
                </select>
              </div>
            ))}
          </div>

          <div className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <label className="text-sm font-medium text-foreground">Monedă</label>
              <select
                value={currency}
                onChange={(e) => setCurrency(e.target.value)}
                className="rounded-xl border border-border-subtle bg-background px-4 py-2.5 text-sm text-foreground outline-none transition-colors focus:border-brand-cyan"
              >
                {CURRENCIES.map((code) => (
                  <option key={code} value={code}>
                    {code}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-sm font-medium text-foreground">
                Disponibilitate implicită
                <span className="ml-1.5 text-xs font-normal text-foreground-muted">
                  (când coloana nu e recunoscută)
                </span>
              </label>
              <select
                value={defaultAvailability}
                onChange={(e) => setDefaultAvailability(e.target.value as ProductAvailability)}
                className="rounded-xl border border-border-subtle bg-background px-4 py-2.5 text-sm text-foreground outline-none transition-colors focus:border-brand-cyan"
              >
                {AVAILABILITY_OPTIONS.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <button
            type="button"
            onClick={handleConvert}
            className="mt-6 flex w-full items-center justify-center gap-2 rounded-full bg-brand-blue px-6 py-3.5 text-sm font-semibold text-white transition-transform hover:scale-[1.01] active:scale-[0.99] sm:w-auto"
          >
            Convertește
          </button>
        </ResultReveal>
      )}

      {step === "done" && (
        <ResultReveal className="rounded-3xl border border-border-subtle bg-background-elevated p-6 md:p-8">
          <div className="flex items-center gap-2">
            <CheckCircle size={18} weight="fill" className="text-brand-cyan" />
            <h2 className="text-lg font-semibold text-foreground">
              3. Gata - {convertedRows.length} produse convertite
            </h2>
          </div>

          {issues.length > 0 && (
            <div className="mt-4 space-y-1.5 rounded-xl bg-yellow-500/10 px-4 py-3">
              <div className="flex items-center gap-1.5 text-sm font-semibold text-yellow-500">
                <Warning size={15} weight="fill" />
                De verificat înainte să folosești fișierul
              </div>
              {issues.map((issue) => (
                <p key={issue} className="text-sm text-foreground-muted">
                  {issue}
                </p>
              ))}
            </div>
          )}

          <div className="mt-5 overflow-x-auto rounded-xl border border-border-subtle">
            <table className="w-full text-left text-sm">
              <thead className="bg-background text-xs uppercase tracking-wide text-foreground-muted">
                <tr>
                  <th className="px-4 py-2.5">item_id</th>
                  <th className="px-4 py-2.5">title</th>
                  <th className="px-4 py-2.5">price</th>
                  <th className="px-4 py-2.5">availability</th>
                </tr>
              </thead>
              <tbody>
                {convertedRows.slice(0, 5).map((row) => (
                  <tr key={row.item_id} className="border-t border-border-subtle">
                    <td className="px-4 py-2.5 text-foreground-muted">{row.item_id}</td>
                    <td className="px-4 py-2.5 text-foreground">{row.title || "—"}</td>
                    <td className="px-4 py-2.5 text-foreground-muted">{row.price || "—"}</td>
                    <td className="px-4 py-2.5 text-foreground-muted">{row.availability}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {convertedRows.length > 5 && (
              <p className="px-4 py-2.5 text-xs text-foreground-muted">
                + încă {convertedRows.length - 5} produse în fișierul descărcat
              </p>
            )}
          </div>

          <div className="mt-6 flex flex-col gap-3 sm:flex-row">
            <button
              type="button"
              onClick={handleDownload}
              className="flex items-center justify-center gap-2 rounded-full bg-brand-blue px-6 py-3.5 text-sm font-semibold text-white transition-transform hover:scale-[1.01] active:scale-[0.99]"
            >
              <DownloadSimple size={16} weight="bold" />
              Descarcă produse-chatgpt.csv
            </button>
            <button
              type="button"
              onClick={handleReset}
              className="rounded-full border border-border-subtle px-6 py-3.5 text-sm font-semibold text-foreground-muted transition-colors hover:text-foreground"
            >
              Începe din nou
            </button>
          </div>
        </ResultReveal>
      )}
    </div>
  );
}
