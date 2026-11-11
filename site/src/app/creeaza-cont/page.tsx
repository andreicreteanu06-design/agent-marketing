import type { Metadata } from "next";
import { Footer } from "@/components/Footer";
import { SignupForm } from "@/components/SignupForm";
import { AuthFrame } from "@/components/AuthFrame";

export const metadata: Metadata = {
  title: "Creează cont: AC Media Marketing",
  description: "Creează-ți contul de client AC Media și conectează-ți conturile de reclame.",
};

export default function CreeazaContPage() {
  return (
    <>
      <AuthFrame
        title="Creează cont"
        description="Contul tău de client AC Media. După înregistrare, conectezi conturile de reclame din pagina de cont, cu cheile criptate imediat."
      >
        <SignupForm />
      </AuthFrame>
      <Footer />
    </>
  );
}
