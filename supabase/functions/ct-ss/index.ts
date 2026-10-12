import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2";
// ct-ss — daily StockScans pull (needs the session cookie in ct_secret 'stockscans_cookie', JWT lasts ~10-20 days).
// Resumable job list per IST day in ct_snapshot('ss_job'); on HTTP 429 it saves its place and returns
// {more:true, throttled:true} — the next cron tick continues (StockScans allows roughly 50-300 calls per window).
// Jobs: 37 pre-built scans run as "Latest" (the dated snapshot for today is filled in later by StockScans; "Latest" is live)
// stamped with the latest snapshot date, (max 4 pages = top 200 by market cap), concall scan (live
// quarter, all pages), industry + index momentum scores, market breadth, concall/result calendars, IPO board.
const sb = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
const BASE = "https://www.stockscans.in";
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36 Edg/155.0.0.0";
const istDate = () => new Date(Date.now() + 5.5 * 3600e3).toISOString().slice(0, 10);
class Throttled extends Error {}
class AuthFail extends Error {}

Deno.serve(async (req: Request) => {
  const t0 = Date.now(); const u = new URL(req.url); const budget = +(u.searchParams.get("budget") ?? "110") * 1000;
  const day = istDate(); const log: any = { day, calls: 0, rows: 0, done: [] as string[] };
  let job: any = null;
  const save = async () => { if (job) await sb.from("ct_snapshot").upsert({ k: "ss_job", d: day, body: job }, { onConflict: "k,d" }); };
  try {
    const { data: sec } = await sb.from("ct_secret").select("v").eq("k", "stockscans_cookie").single();
    const H: any = { "User-Agent": UA, Accept: "application/json", "Content-Type": "application/json", Cookie: sec!.v,
      Origin: BASE, Referer: BASE + "/stock-scans", "x-sync-source": "aqsa4985mv5fk5yp" };
    const call = async (path: string, body?: any) => {
      log.calls++;
      const r = await fetch(BASE + path, { method: body ? "POST" : "GET", headers: body ? { ...H, "x-sync-skip": "1" } : H, body: body ? JSON.stringify(body) : undefined });
      if (r.status === 429) throw new Throttled("429");
      if (r.status === 401 || r.status === 403) throw new AuthFail(`StockScans ${r.status} — cookie expired? Paste a fresh Copy-as-cURL`);
      if (!r.ok) throw new Error(`StockScans ${r.status} ${path}: ${(await r.text()).slice(0, 150)}`);
      return await r.json();
    };
    const { data: st } = await sb.from("ct_snapshot").select("body").eq("k", "ss_job").eq("d", day).maybeSingle();
    job = st?.body;
    if (!job || u.searchParams.get("reset") === "1") {
      job = { i: 0, list: [{ t: "dates" }, { t: "defs" }, { t: "concall", off: 0 }, { t: "market", kind: "industry" }, { t: "market", kind: "index" },
        { t: "breadth" }, { t: "calendar" }], started: new Date().toISOString() };
    }
    if (job.done_at) return Response.json({ ok: true, more: false, skipped: "already finished today at " + job.done_at });
    while (job.i < job.list.length && Date.now() - t0 < budget) {
      const j = job.list[job.i]; let next = true;
      if (j.t === "dates") {
        const d = await call("/api/scans/stock/historic-ratios-dates");
        job.snap = d.dates?.[0];
      } else if (j.t === "defs") {
        const d = await call("/api/scans/stock/popular");
        const defs = (d.scans ?? []).flat().filter((s: any) => s?.scanId);
        await sb.from("ct_ss_scan_def").upsert(defs.map((s: any) => ({ scan_id: s.scanId, name: s.scanName, scan_type: s.scanType, def: s, updated_at: new Date().toISOString() })), { onConflict: "scan_id" });
        for (const s of defs) job.list.push({ t: "scan", id: s.scanId, off: 0, n: 0 });
      } else if (j.t === "scan") {
        const { data: def } = await sb.from("ct_ss_scan_def").select("def").eq("scan_id", j.id).single();
        const d = await call("/api/scans/stock/run", { ratiosType: "Quick", timePeriod: "Latest", scan: def!.def, watchlistIds: [], order: "desc", orderBy: "Market Capitalization", offset: j.off });
        const tab = d.table ?? []; const ci = (tab[0] ?? []).indexOf("companyId");
        const rows = tab.slice(1).map((r: any[]) => ({ d: job.snap, scan_id: j.id, ss_id: r[ci] }));
        const uq = [...new Map(rows.map((r: any) => [r.ss_id, r])).values()];
        if (uq.length) await sb.from("ct_ss_scan").upsert(uq, { onConflict: "d,scan_id,ss_id", ignoreDuplicates: true });
        j.n += rows.length; j.total = d.total; log.rows += rows.length;
        if (d.end && d.end < (d.total ?? 0) && j.n < 200) { j.off = d.end; next = false; }
      } else if (j.t === "concall") {
        const d = await call("/api/scans/concall/run", { industry: [], index: [], watchlistIds: [], resultTiers: [], sentimentTiers: [],
          filters: [{ left: "Market Capitalization", sign: ">=", right: "100" }], q: "", offset: j.off, quarter: j.quarter ?? null });
        if (!j.quarter && !j.prev && (d.quarters ?? []).length > 1) {
          // previous quarter: fetch fully once (and again on Sundays) so every stock keeps its last concall score
          const pq = d.quarters[1];
          const { count } = await sb.from("ct_ss_concall").select("company_key", { count: "exact", head: true }).eq("quarter", pq);
          if ((count ?? 0) < 300 || new Date(Date.now() + 5.5 * 3600e3).getUTCDay() === 0) job.list.push({ t: "concall", off: 0, quarter: pq, prev: true });
        }
        j.quarter = d.quarter;
        // row: [companyKey, companyId, name, industry, when, ssUrl, src, notesReady, resultScore, sentimentTier, tags, pptSsUrl, congratsCount]
        const rows = (d.rows ?? []).map((r: any[]) => ({ company_key: r[0], quarter: d.quarter, ss_id: r[1], name: r[2], industry: r[3], concall_at: r[4],
          result_score: r[8], sentiment_tier: r[9], tags: r[10] ?? [], congrats: r[12], raw: { ssUrl: r[5], src: r[6], notesReady: r[7], pptSsUrl: r[11] }, fetched_at: new Date().toISOString() }));
        const uniq = [...new Map(rows.map((r: any) => [r.company_key, r])).values()];   // a page can repeat a company
        if (uniq.length) { const { error } = await sb.from("ct_ss_concall").upsert(uniq, { onConflict: "company_key,quarter" }); if (error) throw new Error(error.message); }
        log.rows += rows.length;
        if (d.next != null) { j.off = d.next; next = false; }
      } else if (j.t === "market") {
        const d = await call("/api/scans/market/scores?kind=" + j.kind);
        const rows = (d.rows ?? []).map((r: any) => ({ d: r.date ?? d.date, kind: j.kind, key: r.key, name: r.name, parent: r.parent, score: r.score, status: r.status, raw: r }));
        const uniq = [...new Map(rows.map((r: any) => [r.d + "|" + r.key, r])).values()];
        if (uniq.length) await sb.from("ct_ss_market").upsert(uniq, { onConflict: "d,kind,key" });
        log.rows += rows.length;
      } else if (j.t === "breadth") {
        const d = await call("/api/scans/market/breadth");
        const ind: any = {};
        for (const [k, v] of Object.entries(d.indicators ?? {})) ind[k] = (v as any[]).slice(-260);   // last ~year of daily points
        await sb.from("ct_snapshot").upsert({ k: "ss_breadth", d: day, body: ind }, { onConflict: "k,d" });
      } else if (j.t === "calendar") {
        const a = await call("/api/scans/concall/upcoming", { start: day, days: 21, watchlistIds: [] });
        const b = await call("/api/home/upcoming-results");
        await sb.from("ct_snapshot").upsert({ k: "ss_calendar", d: day, body: { concalls: a.rows ?? [], results: b } }, { onConflict: "k,d" });
      }
      if (next) { log.done.push(j.t + (j.id ? ":" + j.id : j.kind ? ":" + j.kind : "")); job.i++; }
      await save();
      await new Promise((z) => setTimeout(z, 700));
    }
    const finished = job.i >= job.list.length;
    if (finished) {
      job.done_at = new Date().toISOString(); await save();
      await sb.rpc("ct_map_ss");
      const scanRows = job.list.filter((x: any) => x.t === "scan").reduce((s: number, x: any) => s + (x.n ?? 0), 0);
      // an all-empty scan set means StockScans had not computed the day yet: not a valid run
      await sb.from("ct_runs").insert({ kind: scanRows > 0 ? "ss" : "ss_empty", as_of: job.snap ?? day, ok: scanRows > 0, note: { ...log, scanRows, started: job.started } });
    }
    return Response.json({ ok: true, more: !finished, at: job.i, of: job.list.length, ...log, secs: (Date.now() - t0) / 1000 });
  } catch (e) {
    await save();
    if (e instanceof Throttled) return Response.json({ ok: true, more: true, throttled: true, at: job?.i, ...log });
    await sb.from("ct_runs").insert({ kind: e instanceof AuthFail ? "ss_auth_fail" : "ss_fail", as_of: day, ok: false, note: { error: String(e), ...log } });
    return Response.json({ ok: false, error: String(e), ...log }, { status: 500 });
  }
});
