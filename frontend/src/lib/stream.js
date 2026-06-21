export const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

export async function streamPipeline(url, body, handlers = {}) {
  const response = await fetch(url, {
    method: 'POST',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!response.ok || !response.body) {
    throw new Error(`Request failed with HTTP ${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      try {
        const data = JSON.parse(line.slice(6))
        handlers[data.type]?.(data)
        handlers.any?.(data)
      } catch (err) {
        console.warn('Skipping malformed stream line', err)
      }
    }
  }
}
