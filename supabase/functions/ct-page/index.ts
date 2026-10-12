import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2";
// ct-page — serves the Confluence Terminal page data to the Cloudflare Pages worker (which sits behind Cloudflare
// Access). Not public: every request must carry header x-ct-key = ct_secret 'page_key'.
//   GET ?what=data        -> latest page JSON (built nightly by ct_nightly())
//   GET ?card=<ISIN>      -> live dossier for any stock (ct_card)
//   GET ?q=<text>         -> up to 20 stocks matching a symbol / name
const sb = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
let KEY: string | null = null;
Deno.serve(async (req: Request) => {
  try {
    if (!KEY) { const { data } = await sb.from("ct_secret").select("v").eq("k", "page_key").single(); KEY = data?.v ?? null; }
    if (!KEY || req.headers.get("x-ct-key") !== KEY) return new Response("forbidden", { status: 403 });
    const u = new URL(req.url);
    const card = u.searchParams.get("card"), q = u.searchParams.get("q");
    const H = { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" };
    if (card) {
      if (!/^IN[A-Z0-9]{10}$/.test(card)) return new Response("bad isin", { status: 400 });
      const { data, error } = await sb.rpc("ct_card_full", { p_isin: card });
      if (error) throw new Error(error.message);
      return new Response(JSON.stringify(data), { headers: H });
    }
    if (q) {
      const { data, error } = await sb.rpc("ct_search", { p_q: q.slice(0, 40) });
      if (error) throw new Error(error.message);
      return new Response(JSON.stringify(data), { headers: H });
    }
    const { data, error } = await sb.from("ct_page").select("html,built_at").eq("id", "data").single();
    if (error) throw new Error(error.message);
    return new Response(data.html, { headers: { ...H, "x-built-at": data.built_at } });
  } catch (e) {
    return Response.json({ ok: false, error: String(e) }, { status: 500 });
  }
});
