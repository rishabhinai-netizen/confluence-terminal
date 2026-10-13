import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2";
// ct-ingest — bulk upsert for backfills run from a workstation. Gated by ct_secret 'ingest_key' (header x-ct-key).
// Body: { table, rows, on_conflict }. Only whitelisted tables.
const sb = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
const OK = new Set(["ct_es_results", "ct_es_concalls", "ct_es_smart", "ct_es_filings", "ct_ss_scan", "ct_ss_scan_def",
  "ct_ss_concall", "ct_ss_market", "ct_snapshot", "ct_signal_stats", "ct_stock_map", "ct_res", "ct_prices", "ct_concall_lite", "ct_ss_panel"]);
Deno.serve(async (req: Request) => {
  try {
    const { data } = await sb.from("ct_secret").select("v").eq("k", "ingest_key").single();
    if (!data || req.headers.get("x-ct-key") !== data.v) return new Response("forbidden", { status: 403 });
    const b = await req.json();
    if (!OK.has(b.table)) return Response.json({ ok: false, error: "table not allowed" }, { status: 400 });
    const rows = b.rows ?? [];
    for (let i = 0; i < rows.length; i += 500) {
      const { error } = await sb.from(b.table).upsert(rows.slice(i, i + 500), { onConflict: b.on_conflict });
      if (error) return Response.json({ ok: false, error: error.message, at: i }, { status: 500 });
    }
    return Response.json({ ok: true, n: rows.length });
  } catch (e) {
    return Response.json({ ok: false, error: String(e) }, { status: 500 });
  }
});
