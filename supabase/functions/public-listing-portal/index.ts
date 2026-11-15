import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const corsOrigins = new Set([
  "https://mickaelwhitecap.github.io",
  "http://localhost:5500",
  "http://127.0.0.1:5500",
]);

function response(req: Request, body: unknown, status = 200) {
  const origin = req.headers.get("Origin") || "";
  const headers = new Headers({
    "Content-Type": "application/json",
    "Vary": "Origin",
  });
  if (corsOrigins.has(origin)) {
    headers.set("Access-Control-Allow-Origin", origin);
    headers.set("Access-Control-Allow-Headers", "apikey, content-type");
    headers.set("Access-Control-Allow-Methods", "POST, OPTIONS");
  }
  return new Response(JSON.stringify(body), { status, headers });
}

async function sha256(value: string) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest)).map((x) => x.toString(16).padStart(2, "0")).join("");
}

function adminClient() {
  const url = Deno.env.get("SUPABASE_URL");
  const secrets = Deno.env.get("SUPABASE_SECRET_KEYS");
  const legacy = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  let key = legacy || "";
  if (secrets) {
    try {
      const parsed = JSON.parse(secrets);
      key = parsed.default || Object.values(parsed)[0] || key;
    } catch { /* use legacy secret when present */ }
  }
  if (!url || !key) throw new Error("Portal service is not configured");
  return createClient(url, key, { auth: { persistSession: false, autoRefreshToken: false } });
}

const editableFields = new Set(["a", "p", "e", "w", "h", "s", "d"]);
const limits: Record<string, number> = { a: 240, p: 100, e: 180, w: 500, h: 300, s: 500, d: 3000 };

function cleanPatch(input: unknown): Record<string, string | null> {
  if (!input || typeof input !== "object" || Array.isArray(input)) throw new Error("Los datos enviados no son válidos.");
  const patch: Record<string, string | null> = {};
  for (const [key, raw] of Object.entries(input as Record<string, unknown>)) {
    if (!editableFields.has(key) || typeof raw !== "string") throw new Error("Se ha incluido un campo no permitido.");
    const value = raw.trim();
    if (value.length > limits[key]) throw new Error("Uno de los campos supera la longitud permitida.");
    // Un campo vacío representa una petición explícita de borrado.
    patch[key] = value === "" ? null : value;
  }
  if (patch.e && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(patch.e)) throw new Error("El correo electrónico no tiene un formato válido.");
  if (patch.w) {
    let url: URL;
    try { url = new URL(patch.w); } catch { throw new Error("La página web debe ser una URL completa."); }
    if (!["http:", "https:"].includes(url.protocol)) throw new Error("La página web debe comenzar por http:// o https://.");
  }
  if (!Object.keys(patch).length) throw new Error("No se han recibido campos para actualizar.");
  return patch;
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return response(req, { ok: true });
  if (req.method !== "POST") return response(req, { error: "Método no permitido." }, 405);
  const origin = req.headers.get("Origin") || "";
  if (origin && !corsOrigins.has(origin)) return response(req, { error: "Origen no autorizado." }, 403);

  try {
    const body = await req.json();
    const token = typeof body.token === "string" ? body.token.trim() : "";
    if (!/^[A-Za-z0-9_-]{40,60}$/.test(token)) return response(req, { error: "El enlace no es válido o ha caducado." }, 401);
    const supabase = adminClient();
    const tokenHash = await sha256(token);
    const { data: access, error: accessError } = await supabase
      .from("listing_access_tokens")
      .select("id, listing_id, expires_at, revoked_at")
      .eq("token_hash", tokenHash)
      .maybeSingle();
    if (accessError || !access || access.revoked_at || new Date(access.expires_at).getTime() <= Date.now()) {
      return response(req, { error: "El enlace no es válido, ha caducado o ha sido revocado." }, 401);
    }

    const { data: listing, error: listingError } = await supabase
      .from("listings")
      .select("id, data, is_published, is_deleted")
      .eq("id", access.listing_id)
      .maybeSingle();
    if (listingError || !listing || !listing.is_published || listing.is_deleted) {
      return response(req, { error: "La ficha ya no está disponible para colaboración." }, 404);
    }

    await supabase.from("listing_access_tokens").update({ last_used_at: new Date().toISOString() }).eq("id", access.id);

    if (body.action === "read") {
      const data = listing.data || {};
      const safe = Object.fromEntries(["n", "t", "c", "a", "p", "e", "w", "h", "s", "d"].map((key) => [key, data[key] ?? ""]));
      return response(req, { listing: safe });
    }

    if (body.action === "submit") {
      let patch: Record<string, string | null>;
      try { patch = cleanPatch(body.fields); }
      catch (error) { return response(req, { error: error instanceof Error ? error.message : "Los datos enviados no son válidos." }, 400); }
      const changed = Object.entries(patch).filter(([key, value]) => String(listing.data?.[key] ?? "").trim() !== String(value ?? "").trim());
      if (!changed.length) return response(req, { error: "No hay cambios nuevos que enviar." }, 400);
      const safePatch = Object.fromEntries(changed);
      const fields = {
        n: String(listing.data?.n || ""),
        t: String(listing.data?.t || "negocio"),
        c: String(listing.data?.c || ""),
        _xiclana_update_target_id: listing.id,
        _xiclana_update_patch: safePatch,
      };
      const { error: proposalError } = await supabase.from("listing_proposals").insert({
        fields,
        source_name: "Formulario privado de Xiclana",
        source_url: null,
        source_checked_at: new Date().toISOString().slice(0, 10),
        notes: "Propuesta enviada mediante enlace privado. Pendiente de revisión administrativa.",
        status: "pending",
      });
      if (proposalError) return response(req, { error: "No se ha podido guardar la propuesta. Inténtalo más tarde." }, 500);
      return response(req, { ok: true });
    }

    return response(req, { error: "Acción no reconocida." }, 400);
  } catch (error) {
    console.error("Private listing portal request failed", error);
    return response(req, { error: "No se ha podido procesar la solicitud. Inténtalo más tarde." }, 500);
  }
});