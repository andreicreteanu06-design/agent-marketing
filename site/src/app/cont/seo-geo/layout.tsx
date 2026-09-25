import { SeoGeoSessionProvider } from "@/components/seo-geo/SeoGeoSession";
import { SeoGeoSidebar } from "@/components/seo-geo/SeoGeoSidebar";

/**
 * Modulul SEO + GEO: meniu lateral (Privire de ansamblu, Audit site, Integrari,
 * Setari) si continutul paginii alaturi - o aplicatie, nu o pagina lunga.
 * Fara footer-ul de marketing, ca in orice interfata de lucru. Navbar-ul vine
 * din layout-ul radacina; intre paginile modulului se schimba doar <main>
 * (vezi template.tsx si loading.tsx de langa).
 */
export default function SeoGeoLayout({ children }: LayoutProps<"/cont/seo-geo">) {
  return (
    <SeoGeoSessionProvider>
      <div className="mx-auto max-w-7xl px-6 pb-28 pt-24 lg:flex lg:gap-10 lg:px-8">
        <SeoGeoSidebar />
        <main className="min-w-0 flex-1">{children}</main>
      </div>
    </SeoGeoSessionProvider>
  );
}
