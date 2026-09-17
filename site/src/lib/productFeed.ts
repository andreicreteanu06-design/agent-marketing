/**
 * Conversie catalog client (CSV/XML, coloane arbitrare) -> feed de produse in
 * formatul Agentic Commerce Protocol (ChatGPT Shopping), cf. schema publica
 * https://developers.openai.com/commerce/specs/file-upload/products (verificat
 * explicit - nu presupus). Doar conversie + descarcare: NU trimite nimic catre
 * OpenAI (accesul API real e limitat la parteneri aprobati - vezi
 * ppc_agent/providers/live/__init__.py::LiveGenerativeEngineProvider).
 *
 * Pur client-side (fara backend): fisierul brut al clientului nu paraseste
 * browser-ul lui.
 */

import Papa from "papaparse";

export type ProductAvailability =
  | "in_stock"
  | "out_of_stock"
  | "pre_order"
  | "backorder"
  | "unknown";

export type ProductCondition = "new" | "refurbished" | "used";

/** Cele 9 campuri obligatorii + o selectie curatata de optionale cu valoare reala. */
export interface ChatGptProductRow {
  item_id: string;
  title: string;
  description: string;
  url: string;
  brand: string;
  seller_name: string;
  image_url: string;
  availability: ProductAvailability;
  price: string;
  sale_price: string;
  gtin: string;
  mpn: string;
  condition: ProductCondition | "";
  product_category: string;
  additional_image_urls: string;
}

export const OUTPUT_COLUMNS: (keyof ChatGptProductRow)[] = [
  "item_id",
  "title",
  "description",
  "url",
  "brand",
  "seller_name",
  "image_url",
  "availability",
  "price",
  "sale_price",
  "gtin",
  "mpn",
  "condition",
  "product_category",
  "additional_image_urls",
];

export interface FieldSpec {
  key: keyof ChatGptProductRow;
  label: string;
  required: boolean;
  hint?: string;
  aliases: string[];
}

/** Camp cu camp - vezi docstring-ul modulului pentru sursa specificatiei. */
export const PRODUCT_FIELDS: FieldSpec[] = [
  { key: "item_id", label: "ID produs", required: true, aliases: ["id", "sku", "product id", "item id", "cod produs", "cod"] },
  { key: "title", label: "Titlu", required: true, aliases: ["title", "name", "product name", "nume", "nume produs", "denumire"] },
  { key: "description", label: "Descriere", required: true, aliases: ["description", "descriere", "desc"] },
  { key: "url", label: "Link produs", required: true, aliases: ["url", "link", "product url", "pagina", "product link"] },
  { key: "brand", label: "Brand", required: true, aliases: ["brand", "marca", "producator", "manufacturer"] },
  { key: "seller_name", label: "Nume vânzător", required: true, aliases: ["seller", "seller name", "vanzator", "vânzător", "nume magazin", "denumire magazin", "nume furnizor", "store name"] },
  { key: "image_url", label: "Imagine (URL)", required: true, aliases: ["image", "image url", "imagine", "photo", "picture", "poza", "poza produs"] },
  { key: "availability", label: "Disponibilitate", required: true, hint: "in_stock / out_of_stock / pre_order / backorder", aliases: ["availability", "stock status", "in stock", "disponibilitate", "stare stoc", "stoc"] },
  { key: "price", label: "Preț", required: true, hint: "număr - moneda se adaugă automat mai jos", aliases: ["price", "pret", "preț", "cost"] },
  { key: "sale_price", label: "Preț redus", required: false, aliases: ["sale price", "discount price", "pret redus", "preț redus", "pret promotie"] },
  { key: "gtin", label: "GTIN / EAN / UPC", required: false, aliases: ["gtin", "ean", "upc", "barcode", "cod de bare"] },
  { key: "mpn", label: "MPN (cod producător)", required: false, aliases: ["mpn", "manufacturer part number"] },
  { key: "condition", label: "Stare", required: false, hint: "new / refurbished / used", aliases: ["condition", "stare", "conditie", "condiție"] },
  { key: "product_category", label: "Categorie", required: false, aliases: ["category", "categorie", "product category", "categorie produs"] },
  { key: "additional_image_urls", label: "Imagini suplimentare", required: false, aliases: ["additional images", "gallery", "imagini suplimentare"] },
];

export type Mapping = Partial<Record<keyof ChatGptProductRow, string | null>>;

export interface ParsedSource {
  columns: string[];
  rows: Record<string, string>[];
}

/**
 * Potriveste automat coloanele sursei cu campurile tinta, caz-insensitiv.
 *
 * DOUA TRECERI GLOBALE (nu per-camp): intai potriviri EXACTE pentru toate
 * campurile, abia apoi potriviri prin substring pentru ce a ramas nemapat.
 * Esential - un substring slab pentru un camp procesat mai devreme (ex.
 * "stoc" -> "Stoc Cantitativ" pentru disponibilitate) nu mai fura o coloana
 * de care alt camp avea nevoie printr-o potrivire exacta, mai buna (ex.
 * "Stare Stoc" == alias exact al aceluiasi camp). Descoperit testand pe un
 * export real cu 56 de coloane (vezi conversatia) - un fisier sintetic mic nu
 * a scos la iveala aceasta capcana.
 */
export function autoMapColumns(columns: string[]): Mapping {
  const lowerColumns = columns.map((c) => [c, c.trim().toLowerCase()] as const);
  const used = new Set<string>();
  const mapping: Mapping = {};
  for (const field of PRODUCT_FIELDS) mapping[field.key] = null;

  for (const field of PRODUCT_FIELDS) {
    const match = lowerColumns.find(
      ([orig, lower]) => !used.has(orig) && field.aliases.includes(lower)
    );
    if (match) {
      mapping[field.key] = match[0];
      used.add(match[0]);
    }
  }

  for (const field of PRODUCT_FIELDS) {
    if (mapping[field.key]) continue;
    const match = lowerColumns.find(
      ([orig, lower]) => !used.has(orig) && field.aliases.some((alias) => lower.includes(alias))
    );
    if (match) {
      mapping[field.key] = match[0];
      used.add(match[0]);
    }
  }

  return mapping;
}

export function parseCsvText(text: string): ParsedSource {
  const result = Papa.parse<Record<string, string>>(text, {
    header: true,
    skipEmptyLines: true,
    transformHeader: (header) => header.trim(),
  });
  if (result.errors.length > 0) {
    const first = result.errors[0];
    throw new Error(`CSV invalid (rândul ${first.row ?? "?"}): ${first.message}`);
  }
  return { columns: result.meta.fields ?? [], rows: result.data };
}

/** Extrage randuri dintr-un XML generic: elementul repetat cel mai frecvent = "un produs". */
export function parseXmlToRows(xmlText: string): ParsedSource {
  const doc = new DOMParser().parseFromString(xmlText, "application/xml");
  if (doc.querySelector("parsererror")) {
    throw new Error("Fișierul XML nu poate fi parsat (format invalid).");
  }
  if (!doc.documentElement) {
    throw new Error("Fișierul XML e gol.");
  }

  const tagGroups = new Map<string, Element[]>();
  const walk = (el: Element): void => {
    for (const child of Array.from(el.children)) {
      const list = tagGroups.get(child.tagName) ?? [];
      list.push(child);
      tagGroups.set(child.tagName, list);
      walk(child);
    }
  };
  walk(doc.documentElement);

  let bestList: Element[] = [];
  for (const list of tagGroups.values()) {
    if (list.length > bestList.length) {
      bestList = list;
    }
  }
  if (bestList.length < 2) {
    throw new Error(
      "Nu am găsit un element repetat în XML (un tag per produs, ex. <item> sau <product>)."
    );
  }

  const columnSet = new Set<string>();
  const rows = bestList.map((el) => {
    const row: Record<string, string> = {};
    for (const child of Array.from(el.children)) {
      if (child.children.length === 0) {
        row[child.tagName] = child.textContent?.trim() ?? "";
        columnSet.add(child.tagName);
      }
    }
    for (const attr of Array.from(el.attributes)) {
      const key = `@${attr.name}`;
      row[key] = attr.value;
      columnSet.add(key);
    }
    return row;
  });

  return { columns: Array.from(columnSet), rows };
}

const AVAILABILITY_ALIASES: Record<string, ProductAvailability> = {
  "in stock": "in_stock",
  instock: "in_stock",
  available: "in_stock",
  yes: "in_stock",
  true: "in_stock",
  da: "in_stock",
  "1": "in_stock",
  "in stoc": "in_stock",
  "out of stock": "out_of_stock",
  outofstock: "out_of_stock",
  unavailable: "out_of_stock",
  no: "out_of_stock",
  false: "out_of_stock",
  nu: "out_of_stock",
  "0": "out_of_stock",
  "stoc epuizat": "out_of_stock",
  preorder: "pre_order",
  "pre-order": "pre_order",
  "pre order": "pre_order",
  precomanda: "pre_order",
  "precomandă": "pre_order",
  backorder: "backorder",
  "back order": "backorder",
};

export function normalizeAvailability(
  raw: string,
  fallback: ProductAvailability
): ProductAvailability {
  const key = raw.trim().toLowerCase();
  if (!key) return fallback;
  return AVAILABILITY_ALIASES[key] ?? fallback;
}

const CONDITION_ALIASES: Record<string, ProductCondition> = {
  new: "new",
  nou: "new",
  used: "used",
  folosit: "used",
  refurbished: "refurbished",
  "recondiționat": "refurbished",
  "recondiționată": "refurbished",
};

export function normalizeCondition(raw: string): ProductCondition | "" {
  const key = raw.trim().toLowerCase();
  return CONDITION_ALIASES[key] ?? "";
}

/** ``"79,99 lei"`` / ``"$79.99"`` / ``"79.99"`` -> ``"79.99 RON"`` (formatul cerut de spec). */
export function formatPrice(raw: string, currency: string): string | null {
  const cleaned = raw.replace(/[^\d.,-]/g, "").trim();
  if (!cleaned) return null;
  // Separatorul zecimal e ultimul "," sau "." din sir; restul se trateaza ca
  // separator de mii si se elimina (acopera "1.234,56" si "1,234.56").
  const lastComma = cleaned.lastIndexOf(",");
  const lastDot = cleaned.lastIndexOf(".");
  let normalized = cleaned;
  if (lastComma > lastDot) {
    normalized = cleaned.replace(/\./g, "").replace(",", ".");
  } else if (lastDot > lastComma) {
    normalized = cleaned.replace(/,/g, "");
  }
  const value = Number.parseFloat(normalized);
  if (!Number.isFinite(value)) return null;
  return `${value.toFixed(2)} ${currency}`;
}

export interface ConversionOptions {
  currency: string;
  defaultAvailability: ProductAvailability;
}

export interface ConversionResult {
  rows: ChatGptProductRow[];
  issues: string[];
}

function getMapped(row: Record<string, string>, mapping: Mapping, key: keyof ChatGptProductRow): string {
  const column = mapping[key];
  if (!column) return "";
  return (row[column] ?? "").trim();
}

/** Aplica maparea + normalizarile peste randurile sursa; colecteaza problemele, nu blocheaza. */
export function convertRows(
  source: Record<string, string>[],
  mapping: Mapping,
  options: ConversionOptions
): ConversionResult {
  const issues: string[] = [];
  const missingRequiredCounts = new Map<string, number>();

  const rows = source.map((sourceRow, index) => {
    const rawPrice = getMapped(sourceRow, mapping, "price");
    const price = formatPrice(rawPrice, options.currency);
    const rawSalePrice = getMapped(sourceRow, mapping, "sale_price");
    const salePrice = rawSalePrice ? formatPrice(rawSalePrice, options.currency) : null;

    const row: ChatGptProductRow = {
      item_id: getMapped(sourceRow, mapping, "item_id") || `produs-${index + 1}`,
      title: getMapped(sourceRow, mapping, "title"),
      description: getMapped(sourceRow, mapping, "description"),
      url: getMapped(sourceRow, mapping, "url"),
      brand: getMapped(sourceRow, mapping, "brand"),
      seller_name: getMapped(sourceRow, mapping, "seller_name"),
      image_url: getMapped(sourceRow, mapping, "image_url"),
      availability: normalizeAvailability(
        getMapped(sourceRow, mapping, "availability"),
        options.defaultAvailability
      ),
      price: price ?? "",
      sale_price: salePrice ?? "",
      gtin: getMapped(sourceRow, mapping, "gtin"),
      mpn: getMapped(sourceRow, mapping, "mpn"),
      condition: normalizeCondition(getMapped(sourceRow, mapping, "condition")),
      product_category: getMapped(sourceRow, mapping, "product_category"),
      additional_image_urls: getMapped(sourceRow, mapping, "additional_image_urls"),
    };

    for (const field of PRODUCT_FIELDS) {
      if (!field.required) continue;
      const value = row[field.key];
      if (!value) {
        missingRequiredCounts.set(field.label, (missingRequiredCounts.get(field.label) ?? 0) + 1);
      }
    }

    return row;
  });

  for (const [label, count] of missingRequiredCounts) {
    issues.push(`${count} produs${count === 1 ? "" : "e"} fără „${label}” (câmp obligatoriu)`);
  }

  return { rows, issues };
}

/** Citeste ``file`` ca text si il parseaza dupa extensie (.csv sau .xml). */
export async function parseSourceFile(file: File): Promise<ParsedSource> {
  const text = await file.text();
  const extension = file.name.split(".").pop()?.toLowerCase();
  if (extension === "xml") return parseXmlToRows(text);
  if (extension === "csv") return parseCsvText(text);
  throw new Error("Format neacceptat - încarcă un fișier .csv sau .xml.");
}

/** CSV final, coloane in ordinea ``OUTPUT_COLUMNS`` - gata de descărcat. */
export function rowsToCsv(rows: ChatGptProductRow[]): string {
  return Papa.unparse({
    fields: OUTPUT_COLUMNS,
    data: rows.map((row) => OUTPUT_COLUMNS.map((column) => row[column])),
  });
}
