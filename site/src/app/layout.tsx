import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import NextTopLoader from "nextjs-toploader";
import "./globals.css";
import { Navbar } from "@/components/Navbar";
import { SmoothScroll } from "@/components/SmoothScroll";
import { ScrollProgress } from "@/components/ScrollProgress";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin", "latin-ext"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin", "latin-ext"],
});

const BRAND_CYAN = "#3fd8e8";

export const metadata: Metadata = {
  title: "AC Media | Agency in a Box",
  description:
    "O agenție de marketing coordonată de cinci agenți AI: strategie, buget, tehnologie, ofertă și piață. Decizii explicabile, cu aprobare umană.",
};

/**
 * Tot ce e aici se monteaza O SINGURA DATA si supravietuieste navigarii:
 * bara de incarcare, grain-ul, bara de scroll si Navbar-ul. Doar `children`
 * (paginile, prin template.tsx) se schimba - meniul nu mai clipeste si nu isi
 * mai reia animatiile la fiecare click.
 */
export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="ro"
      data-theme="dark"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full bg-background text-foreground">
        {/* Porneste in momentul click-ului pe un link intern, inainte ca
            pagina noua sa soseasca de la server - raspuns vizual imediat. */}
        <NextTopLoader
          color={BRAND_CYAN}
          height={2}
          showSpinner={false}
          shadow={`0 0 10px ${BRAND_CYAN},0 0 5px ${BRAND_CYAN}`}
          showForHashAnchor={false}
        />
        <div className="site-atmosphere" aria-hidden="true">
          <span className="site-atmosphere__light" />
        </div>
        <div className="grain-overlay" aria-hidden="true" />
        <ScrollProgress />
        <Navbar />
        <div className="site-content">
          <SmoothScroll>{children}</SmoothScroll>
        </div>
      </body>
    </html>
  );
}
