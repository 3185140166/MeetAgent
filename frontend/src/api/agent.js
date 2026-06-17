const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

/**
 * 流式问答，async generator，逐个 yield SSE 事件对象。
 * 事件类型：session_id / tool_start / tool_done / token / done / error
 */
export async function* streamChat({ question, userId, sessionId, maxTurns = 10 }) {
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
  const res = await fetch(`${API_BASE}/agent/session/${sessionId}`, { cache: 'no-store' })
  if (!res.ok) return null
  return res.json()
}

export async function getSessionSummary(sessionId) {
  const res = await fetch(`${API_BASE}/agent/session/${sessionId}/summary`, { cache: 'no-store' })
  if (!res.ok) return null
  return res.json()
}

export async function deleteSession(sessionId) {
  const res = await fetch(`${API_BASE}/agent/session/${sessionId}`, {
    method: 'DELETE',
    cache: 'no-store',
  })
  if (!res.ok) throw new Error(`删除失败：HTTP ${res.status}`)
}

async function getJson(path) {
  const res = await fetch(`${API_BASE}${path}`, { cache: 'no-store' })
  if (!res.ok) throw new Error(`请求失败：HTTP ${res.status}`)
  return res.json()
}

export function getStats() {
  return getJson('/stats')
}

export function getVectorStats() {
  return getJson('/vector/stats')
}

export function getUsers() {
  return getJson('/users')
}

export function getUserMeetings(userId) {
  return getJson(`/users/${encodeURIComponent(userId)}/meetings`)
}

export function getSessions() {
  return getJson('/sessions')
}

export function getMemories({ userId, query = '', includeInactive = false, limit = 50 } = {}) {
  const params = new URLSearchParams()
  if (userId) params.set('user_id', userId)
  if (query) params.set('query', query)
  if (includeInactive) params.set('include_inactive', 'true')
  params.set('limit', String(limit))
  return getJson(`/memories?${params.toString()}`)
}

export function getAgentTasks({ userId, status = '', limit = 50 } = {}) {
  const params = new URLSearchParams()
  if (userId) params.set('user_id', userId)
  if (status) params.set('status', status)
  params.set('limit', String(limit))
  return getJson(`/agent/tasks?${params.toString()}`)
}

export function getAgentTaskSteps(taskId) {
  return getJson(`/agent/tasks/${encodeURIComponent(taskId)}/steps`)
}

export function getAgentTaskEvents(taskId, afterId = 0) {
  const params = new URLSearchParams()
  if (afterId) params.set('after_id', String(afterId))
  return getJson(`/agent/tasks/${encodeURIComponent(taskId)}/events?${params.toString()}`)
}

export function openAgentTaskEventStream(taskId, afterId = 0) {
  const params = new URLSearchParams()
  if (afterId) params.set('after_id', String(afterId))
  return new EventSource(`${API_BASE}/agent/tasks/${encodeURIComponent(taskId)}/events/stream?${params.toString()}`)
}

export async function createAgentTask({ question, userId, sessionId = null, taskType = 'topic_analysis' }) {
  const res = await fetch(`${API_BASE}/agent/tasks`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    cache: 'no-store',
    body: JSON.stringify({
      question,
      user_id: userId || null,
      session_id: sessionId || null,
      task_type: taskType,
    }),
  })
  if (!res.ok) throw new Error(`创建任务失败：HTTP ${res.status}`)
  return res.json()
}

export async function cancelAgentTask(taskId) {
  const res = await fetch(`${API_BASE}/agent/tasks/${encodeURIComponent(taskId)}/cancel`, {
    method: 'POST',
    cache: 'no-store',
  })
  if (!res.ok) throw new Error(`取消任务失败：HTTP ${res.status}`)
  return res.json()
}

export async function retryAgentTask(taskId) {
  const res = await fetch(`${API_BASE}/agent/tasks/${encodeURIComponent(taskId)}/retry`, {
    method: 'POST',
    cache: 'no-store',
  })
  if (!res.ok) throw new Error(`重试任务失败：HTTP ${res.status}`)
  return res.json()
}

export async function recoverAgentTasks() {
  const res = await fetch(`${API_BASE}/agent/tasks/recover`, {
    method: 'POST',
    cache: 'no-store',
  })
  if (!res.ok) throw new Error(`恢复任务失败：HTTP ${res.status}`)
  return res.json()
}
