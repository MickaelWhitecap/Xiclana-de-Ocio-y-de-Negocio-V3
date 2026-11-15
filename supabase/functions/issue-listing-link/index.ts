import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const ADMIN_ID = "2ebd10a1-fbae-454b-a12b-e1692f1eed17";
const PAGE_BASE = "https://mickaelwhitecap.github.io/Xiclana-de-Ocio-y-de-Negocio-V3";

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function getSecretKey() {
  const secrets = Deno.env.get("SUPABASE_SECRET_KEYS");
  if (secrets) {
    try {
      const parsed = JSON.parse(secrets);
      const key = parsed.default || Object.values(parsed)[0];
      if (typeof key === "string") return key;
    } catch { /* try legacy key */ }
  }
  return Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
}

function getPublishableKey() {
  const keys = Deno.env.get("SUPABASE_PUBLISHABLE_KEYS");
  if (keys) {
    try {
      const parsed = JSON.parse(keys);
      const key = parsed.default || Object.values(parsed)[0];
      if (typeof key === "string") return key;
    } catch { /* try legacy key */ }
  }
  return Deno.env.get("SUPABASE_ANON_KEY") || "";
}

function randomToken() {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  let binary = "";
  bytes.forEach((byte) => binary += String.fromCharCode(byte));
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

async function sha256(value: string) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest)).map((x) => x.toString(16).padStart(2, "0")).join("");
}

Deno.serve(async (req: Request) => {
  if (req.method !== "POST") return response({ error: "Método no permitido." }, 405);
  try {
    const authHeader = req.headers.get("Authorization") || "";
    const bearer = authHeader.match(/^Bearer\s+(.+)$/i)?.[1] || "";
    if (!bearer) return response({ error: "Sesión administrativa requerida." }, 401);

    const url = Deno.env.get("SUPABASE_URL") || "";
    const publishableKey = getPublishableKey();
    const secretKey = getSecretKey();
    if (!url || !publishableKey || !secretKey) throw new Error("El servicio de enlaces no está configurado.");

    const authClient = createClient(url, publishableKey, {
      global: { headers: { Authorization: "Bearer " + bearer } },
      auth: { persistSession: false, autoRefreshToken: false },
    });
    const { data: authData, error: authError } = await authClient.auth.getUser(bearer);
    if (authError || authData.user?.id !== ADMIN_ID) return response({ error: "No tienes permiso para gestionar enlaces." }, 403);

    const admin = createClient(url, secretKey, { auth: { persistSession: false, autoRefreshToken: false } });
    const body = await req.json();
    const listingId = typeof body.listing_id === "string" ? body.listing_id.trim() : "";
    if (!listingId) return response({ error: "Falta el identificador de la ficha." }, 400);

    const { data: listing, error: listingError } = await admin
      .from("listings").select("id, is_published, is_deleted").eq("id", listingId).maybeSingle();
    if (listingError || !listing || !listing.is_published || listing.is_deleted) {
      return response({ error: "La ficha no existe o no está publicada." }, 404);
    }

    if (body.action === "revoke") {
      const { error } = await admin.from("listing_access_tokens")
        .update({ revoked_at: new Date().toISOString() })
        .eq("listing_id", listingId).is("revoked_at", null);
      if (error) throw error;
      return response({ ok: true, revoked: true });
    }
    if (body.action !== "issue") return response({ error: "Acción no reconocida." }, 400);

    const token = randomToken();
    const tokenHash = await sha256(token);
    const now = new Date();
    const expires = new Date(now.getTime() + 30 * 24 * 60 * 60 * 1000).toISOString();

    const { error: revokeError } = await admin.from("listing_access_tokens")
      .update({ revoked_at: now.toISOString() })
      .eq("listing_id", listingId).is("revoked_at", null);
    if (revokeError) throw revokeError;

    const { error: insertError } = await admin.from("listing_access_tokens").insert({
      listing_id: listingId,
      token_hash: tokenHash,
      expires_at: expires,
      created_by: authData.user.id,
    });
    if (insertError) throw insertError;

    return response({
      ok: true,
      expires_at: expires,
      url: PAGE_BASE + "/completar-ficha.html?token=" + encodeURIComponent(token),
    });
  } catch (error) {
    return response({ error: error instanceof Error ? error.message : "Error interno." }, 400);
  }
});