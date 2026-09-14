/**
 * Recreare SVG a semnului AC Media (nor + grafic ascendent + sageata), nu
 * fisierul sursa original (nu am avut acces la el ca fisier, doar ca imagine
 * in conversatie) - inlocuieste cu logo-ul real in `public/` cand il ai la
 * indemana, componenta ramane identica ca API.
 */
export function LogoMark({ size = 32, className }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-hidden="true"
    >
      <defs>
        <linearGradient id="ac-media-gradient" x1="4" y1="40" x2="44" y2="8" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="var(--brand-cyan)" />
          <stop offset="1" stopColor="var(--brand-blue)" />
        </linearGradient>
      </defs>
      <path
        d="M14 34a8 8 0 0 1-1.2-15.9A9 9 0 0 1 30 13.6a7 7 0 0 1 3 13.3V27a7 7 0 0 1-1 13.9H14a7 7 0 0 1 0-14v7.1Z"
        fill="url(#ac-media-gradient)"
        fillOpacity="0.16"
        stroke="url(#ac-media-gradient)"
        strokeWidth="2.2"
        strokeLinejoin="round"
      />
      <rect x="16.5" y="26" width="3.4" height="8" rx="1" fill="url(#ac-media-gradient)" />
      <rect x="22.3" y="21.5" width="3.4" height="12.5" rx="1" fill="url(#ac-media-gradient)" />
      <rect x="28.1" y="24.5" width="3.4" height="9.5" rx="1" fill="url(#ac-media-gradient)" />
      <path
        d="M15 24.5 22 18l4.5 4L37 12.5"
        stroke="url(#ac-media-gradient)"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
      <path d="M31 12 37.5 12 37.5 18.5" stroke="url(#ac-media-gradient)" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      <rect x="38.5" y="16.5" width="3" height="3" rx="0.6" fill="var(--brand-cyan)" />
      <rect x="42.5" y="20.5" width="2.2" height="2.2" rx="0.5" fill="var(--brand-cyan)" opacity="0.7" />
    </svg>
  );
}

export function Logo({ className }: { className?: string }) {
  return (
    <div className={`flex items-center gap-2.5 ${className ?? ""}`}>
      <LogoMark size={30} />
      <span className="text-lg font-bold tracking-tight text-foreground">
        AC <span className="text-brand-cyan">Media</span>
      </span>
    </div>
  );
}
