// API client with optional multiplayer session token.
// The token rides in the X-MP-Token header — a custom header browsers cannot
// forge cross-site without CORS, which doubles as our CSRF protection.

let mpToken = null;

export function setMpToken(token) { mpToken = token; }
export function getMpToken() { return mpToken; }

function headers(extra = {}) {
  const h = { "Accept": "application/json", ...extra };
  if (mpToken) h["X-MP-Token"] = mpToken;
  return h;
}

export async function apiGet(path) {
  const res = await fetch(path, { headers: headers() });
  return handle(res);
}

export async function apiSend(path, method, body) {
  const res = await fetch(path, {
    method,
    headers: headers({ "Content-Type": "application/json" }),
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return handle(res);
}

async function handle(res) {
  let data = null;
  try { data = await res.json(); } catch { /* non-json */ }
  if (!res.ok) {
    const detail = (data && data.error) ? data.error : `HTTP ${res.status}`;
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  return data;
}
