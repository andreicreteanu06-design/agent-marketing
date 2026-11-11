"use client";

import type { ComponentPropsWithRef } from "react";

export type ShinyButtonProps = ComponentPropsWithRef<"button">;

/** 21st.dev-inspired finish; native button semantics and form props are preserved. */
export function ShinyButton({
  children,
  className = "",
  type = "button",
  ...props
}: ShinyButtonProps) {
  return (
    <button type={type} className={`enterprise-button shiny-cta ${className}`} {...props}>
      <span className="shiny-cta__content">{children}</span>
    </button>
  );
}
