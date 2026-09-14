/**
 * Adaptat dupa tehnica "Aurora Background" din Aceternity UI
 * (ui.aceternity.com/components/aurora-background) - benzi de gradient
 * repetate, animate prin background-position (keyframe-ul aurora + clasa
 * .aurora-stripe din globals.css), nu blob-uri individuale. Recolorat in
 * familia de brand (cyan -> albastru -> indigo), nu paleta lor implicita.
 */
export function AuroraBackground() {
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      <div className="aurora-stripe" />
      {/* Zona din stanga (unde sta titlul) ramane lizibila - aurora e vie
          doar in partea dreapta, decorativa, din spatele vizualului. */}
      <div className="absolute inset-0 bg-[linear-gradient(90deg,var(--background)_0%,var(--background)_38%,transparent_68%)]" />
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_0%,transparent_0%,var(--background)_78%)]" />
    </div>
  );
}
