"use client";

import { ShinyButton } from "@/components/ui/shiny-button";

import { useState, type FormEvent } from "react";
// Varianta din nextjs-toploader: router.push porneste si bara de incarcare de sus
// (click-urile pe <Link> o pornesc singure; navigarile din cod, nu).
import { useRouter } from "nextjs-toploader/app";
import Link from "next/link";
import { Field } from "./FormField";
import { ApiError, login } from "@/lib/api";
import { setToken } from "@/lib/auth";

export function LoginForm() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const { access_token } = await login({ email, password });
      setToken(access_token);
      router.push("/cont");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Ceva nu a mers bine. Încearcă din nou.");
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <div className="space-y-5">
        <Field
          label="Email"
          type="email"
          name="email"
          placeholder="tu@companie.ro"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          autoComplete="email"
          disabled={submitting}
        />
        <Field
          label="Parolă"
          type="password"
          name="password"
          placeholder="Parola ta"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          autoComplete="current-password"
          disabled={submitting}
        />
      </div>

      {error && (
        <p role="alert" className="rounded-xl bg-red-500/10 px-4 py-3 text-sm text-red-400">
          {error}
        </p>
      )}

      <ShinyButton
        type="submit"
        disabled={submitting}
        className="w-full rounded-xl px-6 py-3.5 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
      >
        {submitting ? "Se autentifică..." : "Autentificare"}
      </ShinyButton>

      <p className="text-center text-sm text-foreground-muted">
        Nu ai încă un cont?{" "}
        <Link href="/creeaza-cont" className="font-semibold text-brand-cyan hover:underline">
          Creează unul
        </Link>
      </p>
    </form>
  );
}
