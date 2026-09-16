"use client";

import { useEffect } from "react";
import Cal, { getCalApi } from "@calcom/embed-react";
import { CAL_LINK } from "@/lib/config";

// <Cal calLink> vrea doar "username/tip-eveniment", nu URL-ul intreg.
const CAL_PATH = CAL_LINK.replace(/^https?:\/\/(www\.)?cal\.com\//, "");

/**
 * Calendarul Cal.com incorporat direct in pagina (nu doar un link extern) -
 * restilizat pe tema intunecata a site-ului prin cal("ui", ...), separat de
 * config-ul de pe <Cal> (care seteaza tema doar pentru iframe-ul initial).
 */
export function CalEmbed() {
  useEffect(() => {
    (async function () {
      const cal = await getCalApi();
      cal("ui", {
        theme: "dark",
        styles: { branding: { brandColor: "#1450d8" } },
        hideEventTypeDetails: false,
      });
    })();
  }, []);

  return (
    <Cal
      calLink={CAL_PATH}
      config={{ theme: "dark", layout: "month_view" }}
      style={{ width: "100%", height: "100%", overflow: "scroll" }}
    />
  );
}
