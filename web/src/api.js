const BASE = import.meta.env.VITE_API_BASE || "";

async function request(path, options) {
  let response;
  try {
    response = await fetch(`${BASE}${path}`, options);
  } catch {
    throw new Error("Cannot reach the API. Is the Python server running on port 8000?");
  }
  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok || (body && body.ok === false)) {
    throw new Error((body && body.error) || `Request failed with HTTP ${response.status}`);
  }
  return body;
}

export function getConfig() {
  return request("/api/config");
}

export function decide(text) {
  return request("/api/decide", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
}
