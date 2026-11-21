// Saturday Multiverse — API client
export async function apiGet(path) {
  const res = await fetch(path, { headers: { "Accept": "application/json" } });
  return handle(res);
}

export async function apiSend(path, method, body) {
  const res = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
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
