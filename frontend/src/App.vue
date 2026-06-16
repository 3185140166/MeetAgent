<template>
  <AdminPage v-if="isAdminPage" />
  <div v-else class="app">
    <!-- 侧边栏 -->
    <aside class="sidebar">
      <div class="sidebar-header">
        <span class="logo"><span class="logo-mark">M</span>MeetAgent</span>
        <a class="admin-link" href="/admin">数据概览</a>
      </div>

      <!-- 用户 ID 输入 -->
      <div class="user-input">
        <label>用户 ID</label>
        <input v-model="userId" placeholder="留空表示全局" />
      </div>

      <!-- 新建对话 -->
      <button class="new-chat-btn" @click="newChat">＋ 新建对话</button>

      <!-- 会话列表 -->
      <div class="session-list">
        <div
          v-for="s in sessions"
          :key="s.id"
          :class="['session-item', { active: s.id === currentSessionId }]"
          @click="switchSession(s)"
        >
          <span class="session-title">{{ s.title }}</span>
          <button class="del-btn" @click.stop="removeSession(s.id)">×</button>
        </div>
        <div v-if="sessions.length === 0" class="no-sessions">暂无对话</div>
      </div>
    </aside>

    <!-- 主区域 -->
    <main class="main">
      <div class="window-bar">
        <div></div>
        <div class="window-title">MeetAgent</div>
        <a class="window-action" href="/admin">数据概览</a>
      </div>
      <ChatWindow
        :key="chatViewKey"
        :session-id="currentSessionId"
        :user-id="userId"
        :messages="currentMessages"
        :loading="currentLoading"
        @send="sendMessage"
      />
    </main>

    <div v-if="sessionNotices.length" class="background-runs">
      <button
        v-for="notice in sessionNotices"
        :key="notice.session.id"
        :class="['background-run', notice.status]"
        type="button"
        @click="openNoticeSession(notice.session)"
      >
        <span class="run-dot" aria-hidden="true"></span>
        <span class="run-copy">
          <span class="run-title">{{ notice.session.title }}</span>
          <span class="run-desc">{{ noticeText(notice.status) }}</span>
        </span>
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import ChatWindow from './components/ChatWindow.vue'
import AdminPage from './components/AdminPage.vue'
import { getSessionMessages, deleteSession, streamChat } from './api/agent.js'

const isAdminPage = window.location.pathname === '/admin'

// 用户 ID，持久化到 localStorage
const userId = ref(localStorage.getItem('meetagent_user_id') || '')
watch(userId, (v) => localStorage.setItem('meetagent_user_id', v))

// 会话列表，持久化到 localStorage
const SESSIONS_KEY = 'meetagent_sessions'
const sessions = ref(JSON.parse(localStorage.getItem(SESSIONS_KEY) || '[]'))
watch(sessions, (v) => localStorage.setItem(SESSIONS_KEY, JSON.stringify(v)), { deep: true })

const currentSessionId = ref(null)
const messagesBySession = reactive({})
const runningBySession = reactive({})
const completedNoticeBySession = reactive({})
const chatViewKey = ref(0)

const currentMessages = computed(() => {
  if (!currentSessionId.value) return []
  return messagesBySession[currentSessionId.value] || []
})

const currentLoading = computed(() => {
  return Boolean(currentSessionId.value && runningBySession[currentSessionId.value])
})

const sessionNotices = computed(() => {
  return sessions.value
    .filter((s) => s.id !== currentSessionId.value)
    .map((s) => {
      if (runningBySession[s.id]) return { session: s, status: 'running' }
      if (completedNoticeBySession[s.id]) return { session: s, status: 'done' }
      return null
    })
    .filter(Boolean)
})

const isLocalSession = (id) => String(id || '').startsWith('local-')

function ensureSessionMessages(sessionId) {
  if (!messagesBySession[sessionId]) messagesBySession[sessionId] = []
  return messagesBySession[sessionId]
}

function makeLocalSessionId() {
  return `local-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function upsertSession(sessionId, title) {
  if (!sessions.value.find(s => s.id === sessionId)) {
    sessions.value.unshift({
      id: sessionId,
      title: title.slice(0, 20) + (title.length > 20 ? '…' : ''),
      createdAt: new Date().toISOString(),
    })
  }
}

function replaceSessionId(oldId, newId) {
  if (!oldId || oldId === newId) return
  if (messagesBySession[oldId] && !messagesBySession[newId]) {
    messagesBySession[newId] = messagesBySession[oldId]
  }
  delete messagesBySession[oldId]
  if (runningBySession[oldId]) {
    runningBySession[newId] = runningBySession[oldId]
    delete runningBySession[oldId]
  }
  if (completedNoticeBySession[oldId]) {
    completedNoticeBySession[newId] = completedNoticeBySession[oldId]
    delete completedNoticeBySession[oldId]
  }
  const session = sessions.value.find(s => s.id === oldId)
  if (session) session.id = newId
  if (currentSessionId.value === oldId) currentSessionId.value = newId
}

function newChat() {
  currentSessionId.value = null
  chatViewKey.value += 1
}

async function switchSession(s) {
  currentSessionId.value = s.id
  delete completedNoticeBySession[s.id]
  if (messagesBySession[s.id]) {
    chatViewKey.value += 1
    return
  }
  const data = await getSessionMessages(s.id)
  if (data) {
    messagesBySession[s.id] = data.messages.map((m, i) => ({
      id: i,
      role: m.role,
      content: m.content,
      sources: m.sources || [],
      verification: m.verification || null,
      toolCalls: m.tool_calls
        ? m.tool_calls.map(tc => ({ tool: tc.tool, arguments: tc.arguments || {}, status: 'done' }))
        : [],
      toolsExpanded: false,
      streaming: false,
    }))
  } else {
    messagesBySession[s.id] = []
  }
  chatViewKey.value += 1
}

async function removeSession(id) {
  if (!isLocalSession(id)) await deleteSession(id)
  delete messagesBySession[id]
  delete runningBySession[id]
  delete completedNoticeBySession[id]
  sessions.value = sessions.value.filter(s => s.id !== id)
  if (currentSessionId.value === id) newChat()
}

async function sendMessage(question) {
  let sessionId = currentSessionId.value
  const requestSessionId = sessionId && !isLocalSession(sessionId) ? sessionId : null

  if (!sessionId) {
    sessionId = makeLocalSessionId()
    currentSessionId.value = sessionId
    upsertSession(sessionId, question)
  }

  if (runningBySession[sessionId]) return

  const messages = ensureSessionMessages(sessionId)
  messages.push({ id: Date.now(), role: 'user', content: question, sources: [], verification: null, toolCalls: [] })

  const assistantMsg = reactive({
    id: Date.now() + 1,
    role: 'assistant',
    content: '',
    sources: [],
    verification: null,
    toolCalls: [],
    toolsExpanded: false,
    streaming: true,
  })
  messages.push(assistantMsg)
  runningBySession[sessionId] = true
  delete completedNoticeBySession[sessionId]

  let activeSessionId = sessionId

  try {
    for await (const event of streamChat({
      question,
      userId: userId.value,
      sessionId: requestSessionId,
    })) {
      if (event.type === 'session_id') {
        const serverSessionId = event.session_id
        replaceSessionId(activeSessionId, serverSessionId)
        activeSessionId = serverSessionId
        upsertSession(serverSessionId, question)

      } else if (event.type === 'tool_start') {
        assistantMsg.toolCalls.push({ tool: event.tool, arguments: event.arguments || {}, status: 'running' })

      } else if (event.type === 'tool_done') {
        const tc = assistantMsg.toolCalls.find(t => t.tool === event.tool && t.status === 'running')
        if (tc) tc.status = event.failed ? 'failed' : 'done'

      } else if (event.type === 'token') {
        assistantMsg.content += event.content

      } else if (event.type === 'done') {
        assistantMsg.sources = event.sources || []
        assistantMsg.verification = event.verification || null
        assistantMsg.streaming = false

      } else if (event.type === 'error') {
        assistantMsg.content = `出错了：${event.message}`
        assistantMsg.streaming = false
      }
    }
  } catch (e) {
    assistantMsg.content = `网络错误：${e.message}`
    assistantMsg.streaming = false
  } finally {
    assistantMsg.streaming = false
    delete runningBySession[activeSessionId]
    if (currentSessionId.value !== activeSessionId) {
      completedNoticeBySession[activeSessionId] = true
    }
  }
}

function noticeText(status) {
  return status === 'done' ? '回复已完成，点击查看' : '正在后台生成回复，点击查看'
}

async function openNoticeSession(session) {
  delete completedNoticeBySession[session.id]
  await switchSession(session)
}
</script>

<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  height: 100dvh;
  overflow: hidden;
  color: #0f172a;
  background:
    radial-gradient(circle at 18% 8%, rgba(125, 211, 252, 0.42), transparent 28rem),
    radial-gradient(circle at 82% 14%, rgba(196, 181, 253, 0.34), transparent 30rem),
    linear-gradient(135deg, #eef2f7, #dfe7f1 52%, #f8fafc);
}
#app { height: 100dvh; }
button, input, textarea { font: inherit; }
</style>

<style scoped>
.app {
  display: flex;
  height: 100%;
  min-height: 0;
  gap: 14px;
  padding: 14px;
  background: transparent;
}

.sidebar {
  width: 276px;
  min-width: 276px;
  background: rgba(255, 255, 255, 0.58);
  color: #334155;
  display: flex;
  flex-direction: column;
  border: 1px solid rgba(255, 255, 255, 0.76);
  border-radius: 18px;
  box-shadow: 0 24px 60px rgba(15, 23, 42, 0.13);
  backdrop-filter: blur(24px);
  overflow: hidden;
  min-height: 0;
}

.sidebar-header {
  padding: 20px 18px 16px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.2);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.logo {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  font-size: 16px;
  font-weight: 750;
  color: #111827;
}
.logo-mark {
  display: inline-grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: linear-gradient(135deg, #14b8a6, #2563eb);
  color: #fff;
  font-size: 14px;
  box-shadow: 0 8px 20px rgba(20, 184, 166, 0.25);
}
.admin-link {
  color: #0f766e;
  font-size: 12px;
  text-decoration: none;
  white-space: nowrap;
  padding: 5px 8px;
  border-radius: 7px;
  transition: background 0.2s, color 0.2s;
}
.admin-link:hover { color: #0f4f4a; background: rgba(20, 184, 166, 0.13); }

.user-input {
  padding: 16px 18px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.2);
}
.user-input label {
  display: block;
  font-size: 11px;
  color: #64748b;
  margin-bottom: 7px;
  text-transform: uppercase;
  letter-spacing: 0;
  font-weight: 650;
}
.user-input input {
  width: 100%;
  padding: 9px 10px;
  background: rgba(255, 255, 255, 0.68);
  border: 1px solid rgba(148, 163, 184, 0.34);
  border-radius: 11px;
  color: #0f172a;
  font-size: 13px;
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s, background 0.2s;
}
.user-input input:focus {
  border-color: #14b8a6;
  background: rgba(255, 255, 255, 0.95);
  box-shadow: 0 0 0 4px rgba(20, 184, 166, 0.12);
}
.user-input input::placeholder { color: #94a3b8; }

.new-chat-btn {
  margin: 14px 18px;
  padding: 10px 12px;
  background: #111827;
  border: 1px solid rgba(17, 24, 39, 0.08);
  color: #fff;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s, background 0.2s;
  box-shadow: 0 12px 28px rgba(15, 23, 42, 0.18);
}
.new-chat-btn:hover {
  background: #0f766e;
  transform: translateY(-1px);
  box-shadow: 0 16px 34px rgba(15, 23, 42, 0.2);
}

.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 2px 12px 18px;
}
.session-item {
  display: flex;
  align-items: center;
  padding: 10px 10px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
  gap: 6px;
  color: #475569;
}
.session-item:hover { background: rgba(255, 255, 255, 0.72); color: #0f172a; }
.session-item.active {
  background: rgba(20, 184, 166, 0.14);
  color: #0f4f4a;
  box-shadow: inset 3px 0 0 #14b8a6;
}
.session-title {
  flex: 1;
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.del-btn {
  background: none;
  border: none;
  color: #94a3b8;
  font-size: 16px;
  cursor: pointer;
  width: 24px;
  height: 24px;
  border-radius: 6px;
  opacity: 0;
  transition: opacity 0.15s, background 0.15s, color 0.15s;
}
.session-item:hover .del-btn { opacity: 1; }
.del-btn:hover { color: #b91c1c; background: rgba(248, 113, 113, 0.14); }
.no-sessions {
  text-align: center;
  font-size: 12px;
  color: #94a3b8;
  margin-top: 20px;
}

.main {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.62);
  border: 1px solid rgba(255, 255, 255, 0.78);
  border-radius: 18px;
  box-shadow: 0 24px 70px rgba(15, 23, 42, 0.14);
  backdrop-filter: blur(26px);
  min-width: 0;
  min-height: 0;
}

.window-bar {
  position: relative;
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  min-height: 44px;
  padding: 0 16px;
  border-bottom: 1px solid rgba(203, 213, 225, 0.7);
  background: rgba(248, 250, 252, 0.7);
  backdrop-filter: blur(20px);
}

.window-title {
  color: #475569;
  font-size: 13px;
  font-weight: 650;
}

.window-action {
  justify-self: end;
  color: #64748b;
  font-size: 12px;
  font-weight: 650;
  text-decoration: none;
}
.window-action:hover { color: #0f766e; }

.background-runs {
  position: fixed;
  right: 24px;
  top: 24px;
  z-index: 20;
  display: flex;
  width: min(340px, calc(100vw - 48px));
  flex-direction: column;
  gap: 10px;
}

.background-run {
  display: grid;
  grid-template-columns: 10px minmax(0, 1fr);
  gap: 12px;
  align-items: start;
  padding: 12px 14px;
  border: 1px solid rgba(255, 255, 255, 0.78);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.82);
  box-shadow: 0 18px 48px rgba(15, 23, 42, 0.16);
  color: #0f172a;
  cursor: pointer;
  text-align: left;
  backdrop-filter: blur(22px);
  transition: transform 0.18s, box-shadow 0.18s, border-color 0.18s;
}

.background-run:hover {
  transform: translateY(-1px);
  border-color: rgba(20, 184, 166, 0.36);
  box-shadow: 0 22px 54px rgba(15, 23, 42, 0.18);
}

.run-dot {
  width: 8px;
  height: 8px;
  margin-top: 6px;
  border-radius: 50%;
  background: #2563eb;
  box-shadow: 0 0 0 4px rgba(37, 99, 235, 0.12);
  animation: run-pulse 1.2s ease-in-out infinite;
}

.background-run.done .run-dot {
  background: #10b981;
  box-shadow: 0 0 0 4px rgba(16, 185, 129, 0.12);
  animation: none;
}

.background-run.done {
  border-color: rgba(16, 185, 129, 0.26);
}

.run-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.run-title {
  overflow: hidden;
  color: #0f172a;
  font-size: 13px;
  font-weight: 750;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.run-desc {
  color: #64748b;
  font-size: 12px;
}

@keyframes run-pulse {
  0%, 100% {
    opacity: 0.72;
    transform: scale(0.92);
  }
  50% {
    opacity: 1;
    transform: scale(1.1);
  }
}

@media (max-width: 820px) {
  .sidebar {
    width: 220px;
    min-width: 220px;
  }
  .sidebar-header {
    align-items: flex-start;
    flex-direction: column;
  }
}

@media (max-width: 640px) {
  .app {
    flex-direction: column;
    padding: 8px;
    gap: 8px;
  }
  .sidebar {
    width: 100%;
    min-width: 0;
    max-height: 230px;
    box-shadow: none;
    border-radius: 14px;
  }
  .sidebar-header {
    flex-direction: row;
    align-items: center;
  }
  .main { border-radius: 14px; }
  .window-action { display: none; }
  .background-runs {
    right: 12px;
    top: 12px;
    width: calc(100vw - 24px);
  }
}
</style>
