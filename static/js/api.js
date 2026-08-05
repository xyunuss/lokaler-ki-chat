/**
 * Thin wrapper around the backend.
 *
 * The only interesting part is `streamNdjson`: responses arrive as one JSON
 * object per line, so events are handled as they land instead of waiting for
 * the whole body.
 */

export class ApiError extends Error {
  constructor(message, { status = 0, hint = null } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.hint = hint;
  }
}

async function request(path, { method = 'GET', body, signal, headers } = {}) {
  let response;
  try {
    response = await fetch(path, {
      method,
      signal,
      headers: body instanceof FormData ? headers : { 'Content-Type': 'application/json', ...headers },
      body: body instanceof FormData ? body : body ? JSON.stringify(body) : undefined,
    });
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new ApiError('The app is not reachable.', { hint: 'Is the server still running?' });
  }

  if (response.status === 204) return null;

  const payload = await response.json().catch(() => null);

  if (!response.ok) {
    throw new ApiError(payload?.error || `Request failed (${response.status})`, {
      status: response.status,
      hint: payload?.hint ?? null,
    });
  }
  return payload;
}

/** Yields each JSON object of an NDJSON response as it arrives. */
async function* streamNdjson(path, { body, signal } = {}) {
  const response = await fetch(path, {
    method: 'POST',
    signal,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new ApiError(payload?.error || `Request failed (${response.status})`, {
      status: response.status,
      hint: payload?.hint ?? null,
    });
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';

    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        yield JSON.parse(line);
      } catch {
        /* a partial line can never happen here, but never break the stream */
      }
    }
  }

  if (buffer.trim()) {
    try {
      yield JSON.parse(buffer);
    } catch {
      /* ignore trailing noise */
    }
  }
}

export const api = {
  health: () => request('/api/health'),

  models: () => request('/api/models'),
  showModel: (name) => request(`/api/models/${encodeURIComponent(name)}`),
  pullModel: (name, { signal } = {}) => streamNdjson('/api/models/pull', { body: { name }, signal }),

  conversations: (query) =>
    request(`/api/conversations${query ? `?q=${encodeURIComponent(query)}` : ''}`),
  createConversation: (data = {}) => request('/api/conversations', { method: 'POST', body: data }),
  conversation: (id) => request(`/api/conversations/${id}`),
  updateConversation: (id, patch) =>
    request(`/api/conversations/${id}`, { method: 'PATCH', body: patch }),
  deleteConversation: (id) => request(`/api/conversations/${id}`, { method: 'DELETE' }),
  deleteFromMessage: (conversationId, messageId) =>
    request(`/api/conversations/${conversationId}/messages/${messageId}`, { method: 'DELETE' }),
  exportUrl: (id) => `/api/conversations/${id}/export`,

  uploadDocuments: (files) => {
    const form = new FormData();
    for (const file of files) form.append('files', file);
    return request('/api/documents', { method: 'POST', body: form });
  },

  chat: (payload, { signal } = {}) => streamNdjson('/api/chat', { body: payload, signal }),
};
