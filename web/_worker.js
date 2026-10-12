// Cloudflare Pages advanced-mode worker for Confluence Terminal.
// The whole site sits behind Cloudflare Access (only Rishabh's email). This worker serves the static page and
// proxies /api/* to the Supabase edge function ct-page, adding the shared key (Pages secret CT_KEY) server-side,
// so no key or Supabase URL ever reaches the browser.
const FN = "https://ybdqdpwfhgngggaomvqq.supabase.co/functions/v1/ct-page";
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname.startsWith("/api/")) {
      // defence in depth: refuse anything that did not come through Access
      if (!request.headers.get("cf-access-jwt-assertion") && !env.ALLOW_NO_ACCESS) return new Response("forbidden", { status: 403 });
      let target;
      if (url.pathname === "/api/data") target = FN;
      else if (url.pathname === "/api/card") target = FN + "?card=" + encodeURIComponent(url.searchParams.get("isin") || "");
      else if (url.pathname === "/api/q") target = FN + "?q=" + encodeURIComponent(url.searchParams.get("q") || "");
      else return new Response("not found", { status: 404 });
      const r = await fetch(target, { headers: { "x-ct-key": env.CT_KEY } });
      return new Response(r.body, { status: r.status, headers: { "content-type": r.headers.get("content-type") || "application/json", "cache-control": "no-store", "x-built-at": r.headers.get("x-built-at") || "" } });
    }
    const res = await env.ASSETS.fetch(request);
    const h = new Headers(res.headers);
    h.set("x-robots-tag", "noindex, nofollow"); h.set("referrer-policy", "no-referrer"); h.set("x-frame-options", "DENY");
    return new Response(res.body, { status: res.status, headers: h });
  },
};
