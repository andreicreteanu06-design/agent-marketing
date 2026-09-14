"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
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
      <div className="space-y-5 rounded-3xl border border-border-subtle bg-background-elevated p-6 md:p-8">
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

      <button
        type="submit"
        disabled={submitting}
        className="w-full rounded-full bg-brand-blue px-6 py-3.5 text-sm font-semibold text-white transition-transform hover:scale-[1.01] active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-60"
      >
        {submitting ? "Se autentifică..." : "Autentificare"}
      </button>

      <p className="text-center text-sm text-foreground-muted">
        Nu ai încă un cont?{" "}
        <Link href="/creeaza-cont" className="font-semibold text-brand-cyan hover:underline">
          Creează unul
        </Link>
      </p>
    </form>
  );
}
