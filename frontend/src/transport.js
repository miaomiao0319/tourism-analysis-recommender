const base = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')

async function request(path, options) {
  const response = await fetch(base + path, { cache: 'no-store', ...options })
  const result = await response.json()
  if (!response.ok || result.error) {
    const error = new Error(result.error?.message || '服务暂时不可用。')
    error.code = result.error?.code
    throw error
  }
  return result
}

export const client = {
  list: params => request('/attractions?' + new URLSearchParams(params)),
  statistics: params => request('/statistics?' + new URLSearchParams(params)),
  dataset: () => request('/dataset'),
  recommend: (payload) => request('/recommendations', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  detail: (id, batch) => request('/attractions/' + encodeURIComponent(id) + '?batch_id=' + encodeURIComponent(batch)),
}
