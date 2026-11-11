import type { ReactNode } from "react";
import Link from "next/link";
import { ArrowLeft } from "@phosphor-icons/react/dist/ssr";

export function AuthFrame({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <main className="auth-layout mx-auto grid min-h-[calc(100vh-4rem)] max-w-7xl items-center gap-12 px-6 pb-24 pt-28 lg:grid-cols-[minmax(0,1fr)_minmax(0,.88fr)] lg:gap-20 lg:px-8">
      <div className="auth-story relative hidden lg:block">
        <div className="auth-story__graphic" aria-hidden="true">
          <div className="auth-story__orbit">
            {Array.from({ length: 5 }, (_, index) => <span key={index} className={`auth-story__node auth-story__node--${index + 1}`} />)}
            <span className="auth-story__center" />
          </div>
        </div>
        <p className="auth-story__index">AC MEDIA / AGENCY IN A BOX</p>
        <h2 className="auth-story__title">Un sistem clar.<br /><span>Mai mult control.</span></h2>
        <p className="auth-story__copy">Strategia, bugetul, tehnologia, oferta și piața lucrează în același context. Tu decizi ce se aplică.</p>
      </div>

      <div className="auth-card">
        <Link href="/" className="service-back-link mb-10 inline-flex items-center gap-2 text-sm">
          <ArrowLeft size={15} /> Înapoi la site
        </Link>
        <h1 className="auth-card__title">{title}</h1>
        <p className="auth-card__description mt-4 max-w-[46ch] text-base leading-7 text-foreground-muted">{description}</p>
        <div className="mt-9">{children}</div>
      </div>
    </main>
  );
}
