"use client";

import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { useRouter } from "next/navigation";
import { motion, useReducedMotion } from "motion/react";
import {
  ArrowClockwise,
  CaretDown,
  Check,
  Crown,
  PaperPlaneRight,
  Scissors,
} from "@phosphor-icons/react/dist/ssr";
import { Badge } from "@/components/ui/badge";
import {
  ApiError,
  askQueen,
  QUEEN_MAX_QUESTION_CHARS,
  type CouncilTopic,
  type FinancialStatus,
  type QueenChatReply,
} from "@/lib/api";
import { clearToken, getToken } from "@/lib/auth";
import { EASE_OUT } from "@/lib/motion";
import { cn } from "@/lib/utils";

type Turn =
  | { id: number; kind: "client"; text: string }
  | { id: number; kind: "queen"; reply: QueenChatReply }
  | { id: number; kind: "error"; text: string; question: string };
// Omit distributiv: fiecare fel de mesaj isi pastreaza campurile proprii.
type WithoutId<T> = T extends unknown ? Omit<T, "id"> : never;
type NewTurn = WithoutId<Turn>;

const SUGGESTIONS = [
  "Merită să cresc bugetul?",
  "E rentabilă campania mea?",
  "Cine e clientul meu ideal?",
  "Ce zici să intrăm pe TikTok?",
];

const FINANCIAL_BADGE: Record<
  FinancialStatus,
  { label: string; variant: "success" | "danger" | "warning" | "neutral" }
> = {
  profitable: { label: "CFO: rentabil", variant: "success" },
  unprofitable: { label: "CFO: nerentabil", variant: "danger" },
  no_benchmark: { label: "CFO: fără țintă CPA", variant: "warning" },
  insufficient_data: { label: "CFO: date insuficiente", variant: "neutral" },
};

const TOPIC_LABEL: Record<CouncilTopic, string> = {
  budget: "Buget",
  channel: "Canal nou",
  profitability: "Rentabilitate",
  audience: "Public",
  creative: "Reclame",
  general: "Privire de ansamblu",
};

const CHANNEL_NAME: Record<string, string> = {
  tiktok: "TikTok",
  meta: "Meta",
  google: "Google Ads",
  linkedin: "LinkedIn",
  pinterest: "Pinterest",
  snapchat: "Snapchat",
  chatgpt: "ChatGPT",
};

/**
 * Pasii deliberarii, in ordinea in care ii face serverul: datele, apoi
 * strategia de brand si CFO-ul IN PARALEL, apoi sinteza Reginei. Durata reala
 * nu se stie dinainte (un apel HTTP), deci fazele avanseaza pe un ceas si
 * ultima ramane activa pana vine raspunsul.
 */
const DELIBERATION_STEPS: { label: string; phase: number }[] = [
  { label: "Datele contului: căutări, reclame, cheltuieli", phase: 0 },
  { label: "Regina verifică rezonanța cu clientul ideal", phase: 1 },
  { label: "Agentul CFO analizează rentabilitatea", phase: 1 },
  { label: "Sinteza: ce trece, ce se taie", phase: 2 },
];
const DELIBERATION_HEADLINES = [
  "Regina își convoacă consiliul…",
  "Agentul CFO analizează rentabilitatea…",
  "Regina taie ideile neprofitabile și formulează răspunsul…",
];
const PHASE_DELAYS_MS = [900, 3200];

function time(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString("ro-RO", { hour: "2-digit", minute: "2-digit" });
}

function QueenAvatar({ active = false }: { active?: boolean }) {
  return (
    <span className="relative flex h-9 w-9 shrink-0 items-center justify-center">
      {active && (
        <span
          aria-hidden
          className="absolute inset-0 animate-ping rounded-full bg-brand-cyan/20 motion-reduce:animate-none"
        />
      )}
      <span className="relative flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br from-brand-blue to-brand-cyan/80 p-px">
        <span className="flex h-full w-full items-center justify-center rounded-full bg-background">
          <Crown size={16} weight="duotone" className="text-brand-cyan" />
        </span>
      </span>
    </span>
  );
}

function StepIcon({ state }: { state: "done" | "active" | "pending" }) {
  if (state === "done") {
    return (
      <span className="flex h-4 w-4 items-center justify-center rounded-full bg-brand-cyan/15 text-brand-cyan">
        <Check size={10} weight="bold" />
      </span>
    );
  }
  if (state === "active") {
    return (
      <span className="relative flex h-4 w-4 items-center justify-center">
        <span className="absolute h-4 w-4 animate-ping rounded-full bg-brand-cyan/30 motion-reduce:animate-none" />
        <span className="h-1.5 w-1.5 rounded-full bg-brand-cyan" />
      </span>
    );
  }
  return <span className="h-4 w-4 rounded-full border border-border-strong" />;
}

/** Starea "consiliul delibereaza" - distincta de un simplu spinner. */
function Deliberation() {
  const [phase, setPhase] = useState(0);

  useEffect(() => {
    const timers = PHASE_DELAYS_MS.map((delay, index) =>
      window.setTimeout(() => setPhase(index + 1), delay)
    );
    return () => timers.forEach((timer) => window.clearTimeout(timer));
  }, []);

  return (
    <div className="flex gap-3" role="status" aria-live="polite">
      <QueenAvatar active />
      <div className="min-w-0 flex-1 rounded-2xl rounded-tl-md border border-border-subtle bg-white/[0.02] px-4 py-3.5">
        <p className="text-sm font-medium text-foreground">{DELIBERATION_HEADLINES[phase]}</p>
        <div
          aria-hidden
          className="mt-3 h-px w-full overflow-hidden bg-border-subtle"
        >
          <div className="h-px w-1/3 animate-[council-scan_1.6s_ease-in-out_infinite] bg-gradient-to-r from-transparent via-brand-cyan to-transparent motion-reduce:animate-none" />
        </div>
        <ul className="mt-3 space-y-2">
          {DELIBERATION_STEPS.map((step) => {
            const state = phase > step.phase ? "done" : phase === step.phase ? "active" : "pending";
            return (
              <li
                key={step.label}
                className={cn(
                  "flex items-center gap-2.5 text-[13px] transition-colors duration-300",
                  state === "pending" ? "text-foreground-muted/50" : "text-foreground-muted",
                  state === "active" && "text-foreground"
                )}
              >
                <StepIcon state={state} />
                {step.label}
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}

function CouncilDetails({ reply, id }: { reply: QueenChatReply; id: string }) {
  const { ruling } = reply;
  const ref = useRef<HTMLDivElement>(null);
  const reduceMotion = useReducedMotion();

  // Deschisa sub ultimul mesaj, deliberarea ar ramane sub marginea conversatiei.
  useEffect(() => {
    ref.current?.scrollIntoView({ block: "nearest", behavior: reduceMotion ? "auto" : "smooth" });
  }, [reduceMotion]);

  return (
    <div ref={ref} id={id} className="mt-3 space-y-4 border-t border-border-subtle pt-4">
      <div className="grid gap-3 md:grid-cols-2">
        {reply.opinions.map((opinion) => (
          <div
            key={opinion.member}
            className="rounded-xl border border-border-subtle bg-background/60 p-3.5"
          >
            <p className="text-[11px] font-medium uppercase tracking-widest text-foreground-muted">
              {opinion.title}
            </p>
            <p className="mt-2 text-[13px] leading-relaxed text-foreground/90">{opinion.opinion}</p>
            {opinion.source === "template" && (
              <p className="mt-2 text-[11px] text-foreground-muted" title={opinion.fallback_reason ?? undefined}>
                Poziție deterministă, din datele contului
              </p>
            )}
          </div>
        ))}
      </div>

      <div>
        <p className="text-[11px] font-medium uppercase tracking-widest text-foreground-muted">
          Decizia consiliului
        </p>
        <p className="mt-1.5 text-[13px] leading-relaxed text-foreground">{ruling.decision}</p>
      </div>

      {ruling.approved.length > 0 && (
        <div>
          <p className="text-[11px] font-medium uppercase tracking-widest text-foreground-muted">
            Susținut de ambele scaune
          </p>
          <ul className="mt-2 space-y-1.5">
            {ruling.approved.map((idea) => (
              <li key={idea} className="flex gap-2 text-[13px] leading-relaxed text-foreground/90">
                <Check size={14} weight="bold" className="mt-0.5 shrink-0 text-emerald-400" />
                <span>{idea}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {ruling.cut.length > 0 && (
        <div>
          <p className="text-[11px] font-medium uppercase tracking-widest text-foreground-muted">
            Tăiat de CFO
          </p>
          <ul className="mt-2 space-y-1.5">
            {ruling.cut.map((idea) => (
              <li key={idea} className="flex gap-2 text-[13px] leading-relaxed text-foreground/80">
                <Scissors size={14} weight="bold" className="mt-0.5 shrink-0 text-red-300" />
                <span>{idea}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function QueenMessage({ reply }: { reply: QueenChatReply }) {
  const [open, setOpen] = useState(false);
  const detailsId = useId();
  const financial = FINANCIAL_BADGE[reply.financial_status];
  const channel = reply.ruling.new_channel;
  const topic = channel
    ? `${TOPIC_LABEL.channel}: ${CHANNEL_NAME[channel] ?? channel}`
    : TOPIC_LABEL[reply.topic];

  return (
    <div className="flex gap-3">
      <QueenAvatar />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="text-sm font-semibold text-foreground">Regina</span>
          <span className="text-[11px] text-foreground-muted">{time(reply.generated_at)}</span>
        </div>
        <div className="mt-1.5 rounded-2xl rounded-tl-md border border-border-subtle bg-white/[0.03] px-4 py-3.5">
          <p className="whitespace-pre-line text-[15px] leading-relaxed text-foreground">{reply.reply}</p>

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Badge variant={financial.variant}>{financial.label}</Badge>
            <Badge>{topic}</Badge>
            {reply.directive_status !== "ok" && <Badge>Client ideal: date insuficiente</Badge>}
          </div>

          <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
            <p
              className="text-[11px] text-foreground-muted"
              title={reply.fallback_reason ?? undefined}
            >
              {reply.source === "llm"
                ? `Formulat de consiliu · ${reply.model}`
                : "Răspuns determinist, din datele contului"}
            </p>
            <button
              type="button"
              onClick={() => setOpen((value) => !value)}
              aria-expanded={open}
              aria-controls={detailsId}
              className="flex items-center gap-1 text-xs font-medium text-brand-cyan transition-colors hover:text-foreground"
            >
              {open ? "Ascunde deliberarea" : "Vezi deliberarea consiliului"}
              <CaretDown
                size={12}
                weight="bold"
                className={cn("transition-transform duration-300", open && "rotate-180")}
              />
            </button>
          </div>

          {open && <CouncilDetails reply={reply} id={detailsId} />}
        </div>
      </div>
    </div>
  );
}

function ClientMessage({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <p className="max-w-[85%] whitespace-pre-line rounded-2xl rounded-tr-md bg-brand-blue/90 px-4 py-3 text-[15px] leading-relaxed text-white">
        {text}
      </p>
    </div>
  );
}

function QueenIntro() {
  return (
    <div className="flex gap-3">
      <QueenAvatar />
      <div className="min-w-0 flex-1">
        <span className="text-sm font-semibold text-foreground">Regina</span>
        <div className="mt-1.5 rounded-2xl rounded-tl-md border border-border-subtle bg-white/[0.03] px-4 py-3.5 text-[15px] leading-relaxed text-foreground">
          <p>
            Sunt Regina, CMO-ul tău. Nu îți dau sfaturi generice: fiecare întrebare trece prin
            consiliul meu - propria analiză de brand, pe clientul tău ideal, și CFO-ul, pe cifrele
            campaniilor tale.
          </p>
          <p className="mt-2 text-foreground-muted">
            Ideile care nu se susțin financiar se taie înainte să ajungă la tine, iar nimic nu se
            aplică fără aprobarea ta.
          </p>
        </div>
      </div>
    </div>
  );
}

/**
 * Chatul cu Regina: intrebari libere despre campanii, raspunsuri deliberate de
 * consiliu (POST /api/v1/queen/chat). Pagina e protejata client-side, ca restul
 * contului: fara token (sau cu unul expirat - 401) clientul ajunge la login.
 */
export function QueenChat() {
  const router = useRouter();
  const reduceMotion = useReducedMotion();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);
  const nextId = useRef(0);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!getToken()) router.replace("/login");
  }, [router]);

  // Ultimul mesaj (sau deliberarea) mereu in vedere.
  useEffect(() => {
    const container = scrollRef.current;
    if (!container) return;
    container.scrollTo({ top: container.scrollHeight, behavior: reduceMotion ? "auto" : "smooth" });
  }, [turns, pending, reduceMotion]);

  const push = useCallback((turn: NewTurn) => {
    nextId.current += 1;
    const id = nextId.current;
    setTurns((current) => [...current, { ...turn, id } as Turn]);
  }, []);

  const deliberate = useCallback(
    async (question: string) => {
      const token = getToken();
      if (!token) {
        router.replace("/login");
        return;
      }
      setPending(true);
      try {
        const reply = await askQueen(token, question);
        push({ kind: "queen", reply });
      } catch (err: unknown) {
        if (err instanceof ApiError && err.status === 401) {
          clearToken();
          router.replace("/login");
          return;
        }
        const text =
          err instanceof ApiError ? err.message : "Consiliul nu a putut răspunde acum.";
        push({ kind: "error", text, question });
      } finally {
        setPending(false);
        inputRef.current?.focus();
      }
    },
    [push, router]
  );

  function ask(text: string) {
    const question = text.trim();
    if (!question || pending) return;
    push({ kind: "client", text: question });
    setDraft("");
    if (inputRef.current) inputRef.current.style.height = "";
    void deliberate(question);
  }

  function retry(turn: Extract<Turn, { kind: "error" }>) {
    if (pending) return;
    setTurns((current) => current.filter((item) => item.id !== turn.id));
    void deliberate(turn.question);
  }

  function handleChange(event: ChangeEvent<HTMLTextAreaElement>) {
    setDraft(event.target.value);
    const field = event.target;
    field.style.height = "auto";
    field.style.height = `${Math.min(field.scrollHeight, 160)}px`;
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      ask(draft);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    ask(draft);
  }

  const enter = reduceMotion
    ? undefined
    : { initial: { opacity: 0, y: 8 }, animate: { opacity: 1, y: 0 } };
  const remaining = QUEEN_MAX_QUESTION_CHARS - draft.length;

  return (
    <div className="relative flex h-[max(440px,calc(100dvh_-_21rem))] flex-col sm:h-[max(520px,calc(100dvh_-_19rem))] overflow-hidden rounded-3xl border border-border-subtle bg-background-elevated">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-48 bg-[radial-gradient(60%_100%_at_50%_0%,rgba(20,80,216,0.16),transparent)]"
      />

      {/* data-lenis-prevent: Lenis ar prinde rotita pentru pagina, nu pentru conversatie. */}
      <div
        ref={scrollRef}
        data-lenis-prevent
        role="log"
        aria-label="Conversația cu Regina"
        className="relative flex-1 space-y-6 overflow-y-auto overscroll-contain px-4 py-6 sm:px-6"
      >
        <QueenIntro />

        {turns.length === 0 && !pending && (
          <div className="flex flex-wrap gap-2 pl-12">
            {SUGGESTIONS.map((suggestion) => (
              <button
                key={suggestion}
                type="button"
                onClick={() => ask(suggestion)}
                className="rounded-full border border-border-subtle bg-white/[0.02] px-3.5 py-1.5 text-[13px] text-foreground-muted transition-colors hover:border-brand-blue/50 hover:text-foreground"
              >
                {suggestion}
              </button>
            ))}
          </div>
        )}

        {turns.map((turn) => (
          <motion.div key={turn.id} {...enter} transition={{ duration: 0.35, ease: EASE_OUT }}>
            {turn.kind === "client" && <ClientMessage text={turn.text} />}
            {turn.kind === "queen" && <QueenMessage reply={turn.reply} />}
            {turn.kind === "error" && (
              <div className="flex gap-3">
                <QueenAvatar />
                <div className="rounded-2xl rounded-tl-md border border-red-400/20 bg-red-400/[0.05] px-4 py-3">
                  <p className="text-sm text-red-300">{turn.text}</p>
                  <button
                    type="button"
                    onClick={() => retry(turn)}
                    disabled={pending}
                    className="mt-2 flex items-center gap-1.5 text-xs font-semibold text-brand-cyan hover:underline disabled:opacity-40"
                  >
                    <ArrowClockwise size={12} weight="bold" />
                    Întreabă din nou
                  </button>
                </div>
              </div>
            )}
          </motion.div>
        ))}

        {pending && (
          <motion.div {...enter} transition={{ duration: 0.35, ease: EASE_OUT }}>
            <Deliberation />
          </motion.div>
        )}
      </div>

      <form
        onSubmit={handleSubmit}
        className="relative border-t border-border-subtle bg-background-elevated px-4 pb-4 pt-3 sm:px-6"
      >
        <div className="flex items-end gap-2 rounded-2xl border border-border-subtle bg-background px-3 py-2 transition-colors focus-within:border-brand-blue/60">
          <textarea
            ref={inputRef}
            rows={1}
            value={draft}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            maxLength={QUEEN_MAX_QUESTION_CHARS}
            placeholder="Întreab-o pe Regina despre campaniile tale…"
            aria-label="Întrebarea ta pentru Regina"
            className="max-h-40 min-h-9 flex-1 resize-none bg-transparent py-1.5 text-[15px] leading-relaxed text-foreground placeholder:text-foreground-muted/60 focus:outline-none"
          />
          <button
            type="submit"
            disabled={pending || !draft.trim()}
            aria-label="Trimite întrebarea"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-blue text-white transition-[background-color,opacity] hover:bg-brand-blue/90 disabled:opacity-35"
          >
            <PaperPlaneRight size={16} weight="fill" />
          </button>
        </div>
        <div className="mt-2 flex justify-between gap-4 text-[11px] text-foreground-muted">
          <span>Decizia e calculată din datele contului; modelul de limbaj doar o formulează.</span>
          <span className={cn("shrink-0 tabular-nums", remaining > 100 && "sr-only")}>
            {remaining} caractere
          </span>
        </div>
      </form>
    </div>
  );
}
