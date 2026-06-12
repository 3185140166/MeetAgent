const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

/**
 * 流式问答，async generator，逐个 yield SSE 事件对象。
 * 事件类型：session_id / tool_start / tool_done / token / done / error
 */
export async function* streamChat({ question, userId, sessionId, maxTurns = 5 }) {
  const res = await fetch(`${API_BASE}/agent/qa/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      question,
      user_id: userId || null,
      session_id: sessionId || null,
      max_turns: maxTurns,
    }),
  })

  if (!res.ok) throw new Error(`请求失败：HTTP ${res.status}`)

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() // 保留不完整行
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try { yield JSON.parse(line.slice(6)) } catch {}
      }
    }
  }
}

export async function getSessionMessages(sessionId) {
  const res = await fetch(`${API_BASE}/agent/session/${sessionId}`)
  if (!res.ok) return null
  return res.json()
}

export async function deleteSession(sessionId) {
  await fetch(`${API_BASE}/agent/session/${sessionId}`, { method: 'DELETE' })
}
