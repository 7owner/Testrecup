export async function connect(payload) {
  return request('/backend/connect', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function disconnect() {
  return request('/backend/disconnect', { method: 'POST' });
}

export async function poll() {
  return request('/backend/poll');
}

export async function getSession() {
  return request('/backend/session');
}

async function request(url, options = {}) {
  const response = await fetch(url, options);
  const text = await response.text();
  let data = {};

  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { message: text };
    }
  }

  if (!response.ok) {
    const detailText =
      typeof data?.details === 'string'
        ? data.details
        : data?.details?.message || data?.details?.raw || '';
    const msg = [data.message || `HTTP ${response.status}`, detailText].filter(Boolean).join(' | ');
    throw new Error(msg);
  }

  return data;
}
