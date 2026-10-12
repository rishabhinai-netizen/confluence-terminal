import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2";
import { createHash } from "node:crypto";
// ct-es — daily EquiSense pull. Resumable: a job list per day kept in ct_snapshot('es_job', today); each call works
// ~110 s and returns {more:true} until the list is done. Safe to call repeatedly (cron every 10 min in the evening).
// Jobs: results + concalls of the live season quarter (full), previous quarter on Sundays, smart money (7 days),
// catalysts (orders / capex / open offers / business updates, newest 200 each).
const sb = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
const BASE = "https://equisense.ai";
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36";
const iso = (ms: number | null) => (ms ? new Date(ms).toISOString() : null);
const istDate = () => new Date(Date.now() + 5.5 * 3600e3).toISOString().slice(0, 10);
// quarter being reported now: Jan-Mar -> Q3 (Oct-Dec), Apr-Jun -> Q4, Jul-Sep -> Q1, Oct-Dec -> Q2; FY = fiscal year of that quarter
function seasonQ(d = new Date(Date.now() + 5.5 * 3600e3)): [number, number] {
  const m = d.getUTCMonth() + 1, y = d.getUTCFullYear();
  if (m <= 3) return [3, y]; if (m <= 6) return [4, y]; if (m <= 9) return [1, y + 1]; return [2, y + 1];
}
const prevQ = ([q, fy]: [number, number]): [number, number] => (q === 1 ? [4, fy - 1] : [q - 1, fy]);
// same id recipe as research/load_es_history.py (md5 of the joined key fields; Python's str(None) == "None")
function md5(s: string) { return createHash("md5").update(s).digest("hex"); }
function resRow(r: any) {
  return { id: r.id, isin: r.isin, symbol: r.symbol, q: r.quarter, fy: r.fy, announced_at: iso(r.resultAnnouncementEpoch), ecs: r.ecsScore,
    verdict: r.resultVerdict, pead_label: r.peadLabel, pead_index: r.peadIndex, bsh: r.balanceSheetHealth, raw: r, fetched_at: new Date().toISOString() };
}
function ccRow(r: any) {
  return { id: r.id, isin: r.isin, symbol: r.symbol, q: r.quarter, fy: r.year, concall_at: iso(r.concallEventEpoch), guidance_revision: r.guidanceRevision,
    guidance_delivery: r.guidanceDelivery, tone: r.managementTone, candor: r.managementCandor, earnings_quality: r.earningsQuality,
    analyst_sentiment: r.analystSentiment, story_type: r.storyType, raw: r, fetched_at: new Date().toISOString() };
}
function smartRow(r: any) {
  const id = md5(["source", "dealDate", "isin", "dealType", "netQuantity", "topCounterparty", "personCategory", "mode"].map((k) => String(r[k] ?? "None")).join("|"));
  return { id, source: r.source, deal_date: r.dealDate, isin: r.isin, symbol: r.symbol, side: r.dealType, net_value: r.netValueRupees, raw: r, fetched_at: new Date().toISOString() };
}
const filingRow = (r: any, kind: string) => ({ id: r.id, kind, isin: r.isin, symbol: r.symbol, filed_at: iso(r.filedAt), impact: r.impactScore,
  direction: r.impactDirection, raw: r, fetched_at: new Date().toISOString() });

Deno.serve(async (req: Request) => {
  const t0 = Date.now(); const u = new URL(req.url); const budget = +(u.searchParams.get("budget") ?? "110") * 1000;
  const day = istDate(); const log: any = { day, done: [] as string[], rows: 0 };
  try {
    const { data: sec } = await sb.from("ct_secret").select("k,v").eq("k", "equisense_cookie").maybeSingle();
    const H: any = { "User-Agent": UA, Accept: "*/*", Referer: "https://equisense.ai/glance" };
    if (sec?.v) H.Cookie = sec.v;
    const get = async (path: string) => {
      for (let i = 0; i < 4; i++) {
        const r = await fetch(BASE + path, { headers: H });
        if (r.ok) return await r.json();
        if (r.status === 400 || r.status === 403 || r.status === 404) throw new Error(`EquiSense ${r.status} ${path}: ${(await r.text()).slice(0, 150)}`);
        await new Promise((z) => setTimeout(z, 4000 * (i + 1)));
      }
      throw new Error("EquiSense unreachable " + path);
    };
    // job list for today
    let { data: st } = await sb.from("ct_snapshot").select("body").eq("k", "es_job").eq("d", day).maybeSingle();
    let job = st?.body;
    if (!job || u.searchParams.get("reset") === "1") {
      const cur = seasonQ(), prv = prevQ(cur);
      const sunday = new Date(Date.now() + 5.5 * 3600e3).getUTCDay() === 0 || u.searchParams.get("prev") === "1";
      const list: any[] = [
        { t: "results", q: cur[0], fy: cur[1], page: 0 }, { t: "concalls", q: cur[0], fy: cur[1], page: 0 },
        ...["BULK", "BLOCK", "INSIDER", "SAST"].map((s) => ({ t: "smart", src: s, page: 0 })),
        ...["orders", "capex", "open-offers", "updates"].map((k) => ({ t: "filings", kind: k, page: 0, max: 2 })),
      ];
      if (sunday) list.push({ t: "results", q: prv[0], fy: prv[1], page: 0 }, { t: "concalls", q: prv[0], fy: prv[1], page: 0 });
      job = { list, i: 0, started: new Date().toISOString() };
    }
    if (job.done_at) return Response.json({ ok: true, more: false, skipped: "already finished today at " + job.done_at });
    while (job.i < job.list.length && Date.now() - t0 < budget) {
      const j = job.list[job.i]; let more = false; let n = 0;
      if (j.t === "results") {
        const d = await get(`/api/v1/discover/results/glance?page=${j.page}&pageSize=50&quarter=${j.q}&fy=${j.fy}`);
        const rows = (d.content ?? []).filter((r: any) => r.id).map(resRow);
        if (rows.length) { const { error } = await sb.from("ct_es_results").upsert(rows, { onConflict: "id" }); if (error) throw new Error(error.message); }
        n = rows.length; more = !!d.hasNext;
      } else if (j.t === "concalls") {
        const d = await get(`/api/v1/concalls?page=${j.page}&pageSize=100&quarter=${j.q}&fy=${j.fy}`);
        const rows = (d.content ?? []).filter((r: any) => r.id).map(ccRow);
        if (rows.length) { const { error } = await sb.from("ct_es_concalls").upsert(rows, { onConflict: "id" }); if (error) throw new Error(error.message); }
        n = rows.length; more = !!d.hasNext;
      } else if (j.t === "smart") {
        const d = await get(`/api/v1/smart-money/recent?source=${j.src}&days=7&page=${j.page}&pageSize=100`);
        const rows = (d.content ?? []).map(smartRow);
        const uniq = [...new Map(rows.map((r: any) => [r.id, r])).values()];
        if (uniq.length) { const { error } = await sb.from("ct_es_smart").upsert(uniq, { onConflict: "id" }); if (error) throw new Error(error.message); }
        n = uniq.length; more = !!d.hasNext;
      } else if (j.t === "filings") {
        const d = await get(`/api/v1/discover/filings/glance?kind=${j.kind}&page=${j.page}&pageSize=100`);
        const rows = (d.content ?? []).filter((r: any) => r.id).map((r: any) => filingRow(r, j.kind));
        if (rows.length) { const { error } = await sb.from("ct_es_filings").upsert(rows, { onConflict: "id" }); if (error) throw new Error(error.message); }
        n = rows.length; more = !!d.hasNext && j.page + 1 < (j.max ?? 99);
      }
      log.rows += n;
      if (more) j.page++; else { log.done.push(`${j.t}${j.q ? " Q" + j.q + "FY" + j.fy : ""}${j.src ?? ""}${j.kind ? " " + j.kind : ""}`); job.i++; }
      await sb.from("ct_snapshot").upsert({ k: "es_job", d: day, body: job }, { onConflict: "k,d" });
    }
    const finished = job.i >= job.list.length;
    if (finished) {
      job.done_at = new Date().toISOString();
      await sb.from("ct_snapshot").upsert({ k: "es_job", d: day, body: job }, { onConflict: "k,d" });
      await sb.from("ct_runs").insert({ kind: "es", as_of: day, ok: true, note: { ...log, started: job.started } });
    }
    return Response.json({ ok: true, more: !finished, at: job.i, of: job.list.length, ...log, secs: (Date.now() - t0) / 1000 });
  } catch (e) {
    await sb.from("ct_runs").insert({ kind: "es_fail", as_of: day, ok: false, note: { error: String(e), ...log } });
    return Response.json({ ok: false, error: String(e), ...log }, { status: 500 });
  }
});
