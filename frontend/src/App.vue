<template>
  <div class="app">
    <!-- 侧边栏 -->
    <aside class="sidebar">
      <div class="sidebar-header">
        <span class="logo">MeetAgent</span>
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
      <ChatWindow
        :key="currentSessionId || 'new'"
        :session-id="currentSessionId"
        :user-id="userId"
        :initial-messages="currentMessages"
        @session-created="onSessionCreated"
      />
    </main>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import ChatWindow from './components/ChatWindow.vue'
import { getSessionMessages, deleteSession } from './api/agent.js'

// 用户 ID，持久化到 localStorage
const userId = ref(localStorage.getItem('meetagent_user_id') || '')
watch(userId, (v) => localStorage.setItem('meetagent_user_id', v))

// 会话列表，持久化到 localStorage
const SESSIONS_KEY = 'meetagent_sessions'
const sessions = ref(JSON.parse(localStorage.getItem(SESSIONS_KEY) || '[]'))
watch(sessions, (v) => localStorage.setItem(SESSIONS_KEY, JSON.stringify(v)), { deep: true })

const currentSessionId = ref(null)
const currentMessages = ref([])

function newChat() {
  currentSessionId.value = null
  currentMessages.value = []
}

async function switchSession(s) {
  currentSessionId.value = s.id
  const data = await getSessionMessages(s.id)
  if (data) {
    currentMessages.value = data.messages.map((m, i) => ({
      id: i,
      role: m.role,
      content: m.content,
      toolCalls: m.tool_calls
        ? m.tool_calls.map(tc => ({ tool: tc.tool, status: 'done' }))
        : [],
      streaming: false,
    }))
  } else {
    currentMessages.value = []
  }
}

async function removeSession(id) {
  await deleteSession(id)
  sessions.value = sessions.value.filter(s => s.id !== id)
  if (currentSessionId.value === id) newChat()
}

function onSessionCreated(sessionId, firstQuestion) {
  currentSessionId.value = sessionId
  if (!sessions.value.find(s => s.id === sessionId)) {
    sessions.value.unshift({
      id: sessionId,
      title: firstQuestion.slice(0, 20) + (firstQuestion.length > 20 ? '…' : ''),
      createdAt: new Date().toISOString(),
    })
  }
}
</script>

<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  height: 100vh;
  overflow: hidden;
}
#app { height: 100vh; }
</style>

<style scoped>
.app { display: flex; height: 100vh; }

.sidebar {
  width: 240px;
  min-width: 240px;
  background: #1e293b;
  color: #e2e8f0;
  display: flex;
  flex-direction: column;
}

.sidebar-header {
  padding: 18px 16px 12px;
  border-bottom: 1px solid #334155;
}
.logo { font-size: 16px; font-weight: 600; }

.user-input {
  padding: 12px 16px;
  border-bottom: 1px solid #334155;
}
.user-input label {
  display: block;
  font-size: 11px;
  color: #94a3b8;
  margin-bottom: 5px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.user-input input {
  width: 100%;
  padding: 6px 10px;
  background: #334155;
  border: 1px solid #475569;
  border-radius: 6px;
  color: #e2e8f0;
  font-size: 13px;
  outline: none;
}
.user-input input:focus { border-color: #60a5fa; }
.user-input input::placeholder { color: #64748b; }

.new-chat-btn {
  margin: 12px;
  padding: 9px;
  background: #2563eb;
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
  transition: background 0.2s;
}
.new-chat-btn:hover { background: #1d4ed8; }

.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 4px 8px;
}
.session-item {
  display: flex;
  align-items: center;
  padding: 9px 10px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s;
  gap: 6px;
}
.session-item:hover { background: #334155; }
.session-item.active { background: #2563eb; }
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
  padding: 0 2px;
  opacity: 0;
  transition: opacity 0.15s;
}
.session-item:hover .del-btn { opacity: 1; }
.del-btn:hover { color: #f87171; }
.no-sessions {
  text-align: center;
  font-size: 12px;
  color: #64748b;
  margin-top: 20px;
}

.main {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #fff;
}
</style>
