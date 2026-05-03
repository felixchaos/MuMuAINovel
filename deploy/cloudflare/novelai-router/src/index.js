const ROUTE_COOKIE = "novelai_route";
const MAINLAND_COUNTRIES = new Set(["CN"]);
const API_PREFIXES = ["/api", "/health"];
const IMMUTABLE_STATIC_PREFIXES = ["/assets/"];
const IMMUTABLE_STATIC_EXTENSIONS = [
  ".css",
  ".js",
  ".mjs",
  ".svg",
  ".png",
  ".jpg",
  ".jpeg",
  ".webp",
  ".gif",
  ".ico",
  ".woff",
  ".woff2",
];

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const route = chooseRoute(request, url);
    const targetHost = shouldUseCanonicalApi(url) ? env.CN_ORIGIN_HOST : (
      route === "us" ? env.US_ORIGIN_HOST : env.CN_ORIGIN_HOST
    );

    const targetUrl = new URL(request.url);
    targetUrl.protocol = "https:";
    targetUrl.hostname = targetHost;

    const upstreamHeaders = new Headers(request.headers);
    upstreamHeaders.set("X-Forwarded-Host", env.ENTRY_HOST);
    upstreamHeaders.set("X-NovelAI-Route", route);

    const upstreamInit = {
      method: request.method,
      headers: upstreamHeaders,
      redirect: "manual",
    };

    if (request.method !== "GET" && request.method !== "HEAD") {
      upstreamInit.body = request.body;
    }

    const upstreamRequest = new Request(targetUrl.toString(), upstreamInit);

    const upstreamResponse = await fetch(upstreamRequest);
    return normalizeResponse(upstreamResponse, env, route, url);
  },
};

function chooseRoute(request, url) {
  const forced = url.searchParams.get("__route");
  if (forced === "cn" || forced === "us") {
    return forced;
  }

  const cookieRoute = getCookie(request.headers.get("Cookie") || "", ROUTE_COOKIE);
  if (cookieRoute === "cn" || cookieRoute === "us") {
    return cookieRoute;
  }

  const country = String(request.cf?.country || "").toUpperCase();
  if (MAINLAND_COUNTRIES.has(country)) {
    return "cn";
  }

  return "us";
}

function shouldUseCanonicalApi(url) {
  return API_PREFIXES.some((prefix) => url.pathname === prefix || url.pathname.startsWith(prefix));
}

function isImmutableStaticAsset(url) {
  return IMMUTABLE_STATIC_PREFIXES.some((prefix) => url.pathname.startsWith(prefix))
    || IMMUTABLE_STATIC_EXTENSIONS.some((extension) => url.pathname.endsWith(extension));
}

function normalizeResponse(response, env, route, url) {
  const headers = new Headers(response.headers);
  rewriteLocation(headers, env);
  headers.set("X-NovelAI-Route", route);

  if (isImmutableStaticAsset(url)) {
    headers.delete("Set-Cookie");
    headers.set("Cache-Control", "public, max-age=31536000, immutable");
  } else {
    rewriteSetCookies(headers, env, route);
    if (shouldUseCanonicalApi(url)) {
      headers.set("Cache-Control", "no-store");
    } else {
      headers.set("Cache-Control", "no-cache");
    }
  }

  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

function rewriteLocation(headers, env) {
  const location = headers.get("Location");
  if (!location) {
    return;
  }

  const rewritten = location
    .replaceAll(`https://${env.CN_ORIGIN_HOST}`, `https://${env.ENTRY_HOST}`)
    .replaceAll(`http://${env.CN_ORIGIN_HOST}`, `https://${env.ENTRY_HOST}`)
    .replaceAll(`https://${env.US_ORIGIN_HOST}`, `https://${env.ENTRY_HOST}`)
    .replaceAll(`http://${env.US_ORIGIN_HOST}`, `https://${env.ENTRY_HOST}`);

  headers.set("Location", rewritten);
}

function rewriteSetCookies(headers, env, route) {
  const existing = getSetCookieHeaders(headers);
  headers.delete("Set-Cookie");

  for (const cookie of existing) {
    headers.append("Set-Cookie", normalizeCookieDomain(cookie, env));
  }

  headers.append(
    "Set-Cookie",
    `${ROUTE_COOKIE}=${route}; Path=/; Max-Age=3600; SameSite=Lax; Secure`
  );
}

function getSetCookieHeaders(headers) {
  if (typeof headers.getAll === "function") {
    return headers.getAll("Set-Cookie");
  }

  if (typeof headers.getSetCookie === "function") {
    return headers.getSetCookie();
  }

  const single = headers.get("Set-Cookie");
  return single ? [single] : [];
}

function normalizeCookieDomain(cookie, env) {
  const domainPattern = new RegExp(
    `;\\s*Domain=(?:\\.?${escapeRegExp(env.ENTRY_HOST)}|\\.?${escapeRegExp(env.CN_ORIGIN_HOST)}|\\.?${escapeRegExp(env.US_ORIGIN_HOST)})`,
    "ig"
  );
  return cookie.replace(domainPattern, "");
}

function getCookie(cookieHeader, name) {
  for (const part of cookieHeader.split(";")) {
    const [rawName, ...rest] = part.trim().split("=");
    if (rawName === name) {
      return rest.join("=");
    }
  }
  return "";
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
