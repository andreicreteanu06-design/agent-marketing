import type { ChangeEvent } from "react";

export function Field({
  label,
  type = "text",
  placeholder,
  helper,
  name,
  value,
  onChange,
  required,
  autoComplete,
  disabled,
  error,
}: {
  label: string;
  type?: string;
  placeholder?: string;
  helper?: string;
  name?: string;
  value?: string;
  onChange?: (event: ChangeEvent<HTMLInputElement>) => void;
  required?: boolean;
  autoComplete?: string;
  disabled?: boolean;
  error?: string;
}) {
  return (
    <div className="flex flex-col gap-2">
      <label className="text-sm font-medium text-foreground">{label}</label>
      <input
        type={type}
        name={name}
        placeholder={placeholder}
        value={value}
        onChange={onChange}
        required={required}
        autoComplete={autoComplete}
        disabled={disabled}
        className="rounded-xl border border-border-subtle bg-background-elevated px-4 py-3 text-sm text-foreground placeholder:text-foreground-muted/60 outline-none transition-colors focus:border-brand-cyan disabled:cursor-not-allowed disabled:opacity-60"
      />
      {error ? (
        <p className="text-xs text-red-400">{error}</p>
      ) : (
        helper && <p className="text-xs text-foreground-muted">{helper}</p>
      )}
    </div>
  );
}
