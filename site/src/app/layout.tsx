import type { Metadata } from "next";
import { Geist, Geist_Mono, Space_Grotesk } from "next/font/google";
import NextTopLoader from "nextjs-toploader";
import "./globals.css";
import { Navbar } from "@/components/Navbar";
import { SmoothScroll } from "@/components/SmoothScroll";
import { ScrollProgress } from "@/components/ScrollProgress";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

// Doar titlurile (vezi --font-display in globals.css) - corpul de text ramane
// Geist. Space Grotesk are un caracter geometric/tehnic distinct, nu se
// confunda cu Geist-ul de pe orice alt site facut cu un agent AI.
const spaceGrotesk = Space_Grotesk({
  variable: "--font-space-grotesk",
  subsets: ["latin"],
  weight: ["500", "600", "700"],
});

const BRAND_CYAN = "#3fd8e8";

export const metadata: Metadata = {
  title: "AC Media Marketing: PPC gestionat de un agent AI",
  description:
    "Management PPC pe Google, Meta, TikTok și ChatGPT Ads printr-un agent AI cu aprobare umană, plus web design și automatizări AI.",
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
      className={`${geistSans.variable} ${geistMono.variable} ${spaceGrotesk.variable} h-full antialiased`}
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
        <div className="grain-overlay" />
        <ScrollProgress />
        <Navbar />
        <SmoothScroll>{children}</SmoothScroll>
      </body>
    </html>
  );
}
