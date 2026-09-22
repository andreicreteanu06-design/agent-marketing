import type { Metadata } from "next";
import Link from "next/link";
import { ArrowLeft } from "@phosphor-icons/react/dist/ssr";
import { Navbar } from "@/components/Navbar";
import { Footer } from "@/components/Footer";
import { ProductFeedConverter } from "@/components/ProductFeedConverter";

export const metadata: Metadata = {
  title: "Convertor produse pentru ChatGPT: AC Media Marketing",
  description: "Transformă catalogul tău de produse în formatul cerut de ChatGPT Shopping.",
};

export default function ProductFeedPage() {
  return (
    <>
      <Navbar />
      <main className="mx-auto max-w-3xl px-6 pb-28 pt-32 lg:px-8">
        <Link
          href="/cont"
          className="mb-8 inline-flex items-center gap-1.5 text-sm text-foreground-muted hover:text-foreground"
        >
          <ArrowLeft size={14} />
          Contul meu
        </Link>
        <h1 className="text-3xl font-bold tracking-tight text-foreground">
          Convertor produse pentru ChatGPT
        </h1>
        <p className="mt-3 text-base text-foreground-muted">
          Încarcă catalogul tău (CSV, TSV, XML, Excel sau OpenDocument, orice
          coloane) și primești înapoi
          un fișier în formatul cerut de ChatGPT Shopping - gata de trimis când
          ai acces la programul OpenAI pentru comercianți.
        </p>
        <div className="mt-10">
          <ProductFeedConverter />
        </div>
      </main>
      <Footer />
    </>
  );
}
