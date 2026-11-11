import type { Metadata } from "next";
import { Footer } from "@/components/Footer";
import { LoginForm } from "@/components/LoginForm";
import { AuthFrame } from "@/components/AuthFrame";

export const metadata: Metadata = {
  title: "Autentificare: AC Media Marketing",
  description: "Autentifică-te în contul tău de client AC Media.",
};

export default function LoginPage() {
  return (
    <>
      <AuthFrame title="Autentificare" description="Intră în contul tău de client AC Media.">
        <LoginForm />
      </AuthFrame>
      <Footer />
    </>
  );
}
