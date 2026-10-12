import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2";
// ct-prices v3 — mirrors Breakout Playbook's adjusted prices into ct_prices via BP's read-only feed
// (ct_feed_meta_lite / ct_feed_prices / ct_feed_prices_isins; gated by bp_feed_key).
//  * first load (or ?full=1): pages through every ISIN with a cursor (ct_snapshot 'price_cursor'); call repeatedly.
//  * nightly: last ~25 days for every ISIN that traded on BP's last day; any ISIN whose OLDER overlapping bars
//    changed (BP re-adjusted it for a split / bonus / rights) gets its whole history replaced.
// Also refreshes ct_stock names/groups/mcap, ct_market breadth and NSE surveillance flags. Time-boxed (?budget=secs).
const sb = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
const BP = "https://wmmcgeycoacxdvdraewh.supabase.co/rest/v1/rpc/";
const ymd = (d: Date) => d.toISOString().slice(0, 10);
async function paged(q: () => any) {
  const out: any[] = [];
  for (let f = 0; ; f += 1000) {
    const { data, error } = await q().range(f, f + 999);
    if (error) throw new Error(error.message);
    out.push(...(data ?? []));
    if (!data || data.length < 1000) break;
  }
  return out;
}
function recsOf(r: any) { return r.d.map((d: string, j: number) => ({ isin: r.isin, d, o: r.o[j], h: r.h[j], l: r.l[j], c: r.c[j], v: r.v[j] })); }
async function put(recs: any[]) {
  for (let i = 0; i < recs.length; i += 1000) {
    const { error } = await sb.from("ct_prices").upsert(recs.slice(i, i + 1000), { onConflict: "isin,d" });
    if (error) throw new Error("ct_prices " + error.message);
  }
}
Deno.serve(async (req: Request) => {
  const t0 = Date.now(); const u = new URL(req.url);
  const budget = +(u.searchParams.get("budget") ?? "120") * 1000; const full = u.searchParams.get("full") === "1";
  const log: any = { mode: "", isins: 0, rows: 0, readjusted: [] as string[] };
  try {
    const { data: sec } = await sb.from("ct_secret").select("k,v");
    const S: any = Object.fromEntries((sec ?? []).map((r: any) => [r.k, r.v]));
    const H = { apikey: S.bp_anon_key, Authorization: "Bearer " + S.bp_anon_key, "Content-Type": "application/json" };
    const rpc = async (fn: string, body: any) => {
      let last = "";
      for (let i = 0; i < 4; i++) {
        const r = await fetch(BP + fn, { method: "POST", headers: H, body: JSON.stringify({ p_key: S.bp_feed_key, ...body }) });
        if (r.ok) return await r.json();
        last = r.status + " " + (await r.text()).slice(0, 200);
        await new Promise((z) => setTimeout(z, 3000 * (i + 1)));
      }
      throw new Error("BP feed " + fn + ": " + last);
    };
    const meta = await rpc("ct_feed_meta_lite", {});
    const univ = new Map<string, any>((meta.univ ?? []).map((x: any) => [x.isin, x]));
    const st = (meta.meta ?? []).map((m: any) => ({ isin: m.isin, sym: m.sym, name: m.name, grp: m.grp, mcap: univ.get(m.isin)?.mcap ?? null, updated_at: new Date().toISOString() }));
    for (let i = 0; i < st.length; i += 1000) {
      const { error } = await sb.from("ct_stock").upsert(st.slice(i, i + 1000), { onConflict: "isin" });
      if (error) throw new Error("ct_stock " + error.message);
    }
    if (meta.market?.length) await sb.from("ct_market").upsert(meta.market, { onConflict: "d" });
    await sb.from("ct_snapshot").upsert({ k: "bp_flags", d: meta.last_d, body: meta.flags ?? [] }, { onConflict: "k,d" });
    const all: string[] = (meta.isins ?? []).sort();
    const { data: cur } = await sb.from("ct_snapshot").select("body").eq("k", "price_cursor").eq("d", "2000-01-01").maybeSingle();
    let cursor: string | null = full ? "" : (cur?.body?.after ?? null);
    const { count } = await sb.from("ct_prices").select("isin", { count: "exact", head: true });
    if (!count) cursor = cursor ?? "";
    if (cursor !== null) {
      log.mode = "full";
      while (Date.now() - t0 < budget) {
        const rows = await rpc("ct_feed_prices", { p_after: cursor, p_n: 60 });
        if (!rows.length) { cursor = null; break; }
        for (const r of rows) { await put(recsOf(r)); log.isins++; log.rows += r.d.length; }
        cursor = rows[rows.length - 1].isin;
      }
      await sb.from("ct_snapshot").upsert({ k: "price_cursor", d: "2000-01-01", body: { after: cursor } }, { onConflict: "k,d" });
      log.more = cursor !== null; log.cursor = cursor;
    } else {
      log.mode = "incremental";
      const since = ymd(new Date(Date.parse(meta.last_d) - 25 * 86400000));
      const have = new Map<string, number>();
      for (const r of await paged(() => sb.from("ct_prices").select("isin,d,c").gte("d", since).order("isin").order("d"))) have.set(r.isin + "|" + r.d, r.c);
      const redo: string[] = [];
      for (let k = 0; k < all.length; k += 300) {
        const rows = await rpc("ct_feed_prices_isins", { p_isins: all.slice(k, k + 300), p_since: since });
        const ins: any[] = [];
        for (const r of rows) {
          let changed = false;
          r.d.forEach((d: string, j: number) => { const old = have.get(r.isin + "|" + d); if (old !== undefined && Math.abs(old / r.c[j] - 1) > 0.002) changed = true; });
          if (changed) redo.push(r.isin); else ins.push(...recsOf(r));
        }
        await put(ins); log.rows += ins.length; log.isins += rows.length;
      }
      for (let k = 0; k < redo.length && Date.now() - t0 < budget; k += 50) {
        const rows = await rpc("ct_feed_prices_isins", { p_isins: redo.slice(k, k + 50), p_since: "2025-01-01" });
        for (const r of rows) { await sb.from("ct_prices").delete().eq("isin", r.isin); await put(recsOf(r)); log.readjusted.push(r.isin); }
      }
    }
    const { data: mx } = await sb.from("ct_prices").select("d").order("d", { ascending: false }).limit(1);
    log.last_d = mx?.[0]?.d; log.bp_last_d = meta.last_d;
    await sb.from("ct_runs").insert({ kind: "prices", as_of: log.last_d, ok: true, note: log });
    return Response.json({ ok: true, ...log, secs: (Date.now() - t0) / 1000 });
  } catch (e) {
    await sb.from("ct_runs").insert({ kind: "prices_fail", ok: false, note: { error: String(e), ...log } });
    return Response.json({ ok: false, error: String(e), ...log }, { status: 500 });
  }
});
