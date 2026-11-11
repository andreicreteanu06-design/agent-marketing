"use client";

import { ShinyButton } from "@/components/ui/shiny-button";

import { useState, type FormEvent } from "react";
// Varianta din nextjs-toploader: router.push porneste si bara de incarcare de sus
// (click-urile pe <Link> o pornesc singure; navigarile din cod, nu).
import { useRouter } from "nextjs-toploader/app";
import Link from "next/link";
import { Field } from "./FormField";
import { ApiError, signup } from "@/lib/api";
import { setToken } from "@/lib/auth";

export function SignupForm() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const { access_token } = await signup({ name, email, password });
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
          label="Nume"
          name="name"
          placeholder="Numele tău"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          autoComplete="name"
          disabled={submitting}
        />
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
          placeholder="Minimum 8 caractere"
          helper="Stocată criptat, niciodată în clar."
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          autoComplete="new-password"
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
        {submitting ? "Se creează contul..." : "Creează cont"}
      </ShinyButton>

      <p className="text-center text-sm text-foreground-muted">
        Ai deja cont?{" "}
        <Link href="/login" className="font-semibold text-brand-cyan hover:underline">
          Autentifică-te
        </Link>
      </p>
    </form>
  );
}
