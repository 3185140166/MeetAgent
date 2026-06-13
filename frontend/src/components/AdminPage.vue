<template>
  <div class="admin-page">
    <header class="topbar">
      <div>
        <h1>数据概览</h1>
        <p>查看当前本地会议库、结构化记忆和用户数据状态。</p>
      </div>
      <a class="chat-link" href="/">返回聊天</a>
    </header>

    <section class="stats-grid">
      <div v-for="item in statItems" :key="item.label" class="stat-card">
        <span>{{ item.label }}</span>
        <strong>{{ formatNumber(item.value) }}</strong>
      </div>
    </section>

    <section class="content-grid">
      <div class="panel users-panel">
        <div class="panel-head">
          <h2>用户</h2>
          <button @click="loadAll" :disabled="loading">
            {{ loading ? '刷新中' : '刷新' }}
          </button>
        </div>

        <div v-if="error" class="error">{{ error }}</div>
        <div v-else-if="users.length === 0 && !loading" class="empty">
          当前数据库中没有用户数据。
        </div>

        <button
          v-for="u in users"
          :key="u.user_id"
          :class="['user-row', { active: u.user_id === selectedUserId }]"
          @click="selectUser(u.user_id)"
        >
          <div>
            <strong>{{ u.user_id || '未标记用户' }}</strong>
            <span>{{ dateRange(u) }}</span>
          </div>
          <div class="user-counts">
            <span>{{ u.meetings }} 场</span>
            <span>{{ u.summaries }} 已抽取</span>
          </div>
        </button>
      </div>

      <div class="panel meetings-panel">
        <div class="panel-head">
          <h2>会议</h2>
          <button
            v-if="selectedUserId"
            @click="useForChat"
          >
            设为聊天用户
          </button>
        </div>

        <div v-if="!selectedUserId" class="empty">
          选择左侧用户后查看会议列表。
        </div>
        <div v-else-if="meetings.length === 0 && !loadingMeetings" class="empty">
          该用户暂无会议。
        </div>

        <div class="meeting-list">
          <div v-for="m in meetings" :key="m.note_id" class="meeting-row">
            <div>
              <strong>{{ m.title || '未命名会议' }}</strong>
              <span>{{ m.create_time || '无时间' }}</span>
            </div>
            <div class="meeting-meta">
              <span>{{ m.chunks }} chunks</span>
              <span :class="['tag', m.extracted ? 'done' : 'pending']">
                {{ m.extracted ? '已抽取' : '未抽取' }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <div class="panel sessions-panel">
        <div class="panel-head">
          <h2>会话</h2>
          <button @click="loadSessions" :disabled="loadingSessions">
            {{ loadingSessions ? '刷新中' : '刷新' }}
          </button>
        </div>

        <div v-if="sessions.length === 0 && !loadingSessions" class="empty">
          暂无会话记录。
        </div>

        <button
          v-for="s in sessions"
          :key="s.session_id"
          :class="['session-row', { active: s.session_id === selectedSessionId }]"
          @click="selectSession(s.session_id)"
        >
          <div>
            <strong>{{ sessionTitle(s) }}</strong>
            <span>{{ s.user_id || '全局' }} · {{ s.message_count }} 条消息</span>
          </div>
          <div class="session-time">
            <span>{{ s.updated_at }}</span>
          </div>
        </button>
      </div>

      <div class="panel messages-panel">
        <div class="panel-head">
          <h2>会话消息</h2>
          <button
            v-if="selectedSessionId"
            class="danger"
            @click="removeSelectedSession"
          >
            删除会话
          </button>
        </div>

        <div v-if="!selectedSessionId" class="empty">
          选择一个会话后查看消息。
        </div>
        <div v-else class="message-list">
          <div v-for="(m, index) in sessionMessages" :key="index" :class="['message-row', m.role]">
            <div class="message-meta">
              <strong>{{ m.role === 'user' ? '用户' : '助手' }}</strong>
              <span>{{ m.created_at }}</span>
            </div>
            <p>{{ m.content }}</p>
            <div v-if="m.tool_calls?.length" class="tool-list">
              <span v-for="tc in m.tool_calls" :key="tc.tool + tc.turn">
                {{ tc.tool }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import {
  deleteSession,
  getSessionMessages,
  getSessions,
  getStats,
  getUsers,
  getUserMeetings,
} from '../api/agent.js'

const stats = ref(null)
const users = ref([])
const meetings = ref([])
const sessions = ref([])
const sessionMessages = ref([])
const selectedUserId = ref('')
const selectedSessionId = ref('')
const loading = ref(false)
const loadingMeetings = ref(false)
const loadingSessions = ref(false)
const error = ref('')

const statItems = computed(() => {
  const s = stats.value || {}
  return [
    { label: '会议数', value: s.meetings },
    { label: '文本片段', value: s.chunks },
    { label: '会议摘要', value: s.summaries },
    { label: '待办事项', value: s.action_items },
    { label: '决策记录', value: s.decisions },
    { label: '风险项', value: s.risks },
    { label: '实体', value: s.entities },
    { label: '会话数', value: s.chat_sessions },
    { label: '向量索引', value: s.vector_index_count },
  ]
})

function formatNumber(value) {
  return Number(value || 0).toLocaleString()
}

function dateRange(user) {
  if (!user.earliest && !user.latest) return '无时间范围'
  return `${(user.earliest || '').slice(0, 10)} - ${(user.latest || '').slice(0, 10)}`
}

async function loadAll() {
  loading.value = true
  error.value = ''
  try {
    const [statsData, usersData] = await Promise.all([getStats(), getUsers()])
    stats.value = statsData
    users.value = usersData
    await loadSessions()
    if (!selectedUserId.value && usersData.length) {
      await selectUser(usersData[0].user_id)
    }
  } catch (e) {
    error.value = `加载失败：${e.message}`
  } finally {
    loading.value = false
  }
}

async function loadSessions() {
  loadingSessions.value = true
  try {
    sessions.value = await getSessions()
  } catch (e) {
    error.value = `加载会话失败：${e.message}`
  } finally {
    loadingSessions.value = false
  }
}

async function selectUser(userId) {
  selectedUserId.value = userId
  meetings.value = []
  if (!userId) return
  loadingMeetings.value = true
  try {
    meetings.value = await getUserMeetings(userId)
  } catch (e) {
    error.value = `加载会议失败：${e.message}`
  } finally {
    loadingMeetings.value = false
  }
}

async function selectSession(sessionId) {
  selectedSessionId.value = sessionId
  const data = await getSessionMessages(sessionId)
  sessionMessages.value = data?.messages || []
}

async function removeSelectedSession() {
  if (!selectedSessionId.value) return
  await deleteSession(selectedSessionId.value)
  selectedSessionId.value = ''
  sessionMessages.value = []
  await Promise.all([loadSessions(), refreshStats()])
}

async function refreshStats() {
  stats.value = await getStats()
}

function useForChat() {
  localStorage.setItem('meetagent_user_id', selectedUserId.value)
  window.location.href = '/'
}

function sessionTitle(session) {
  const text = session.last_user_message || session.session_id
  return text.length > 28 ? `${text.slice(0, 28)}...` : text
}

onMounted(loadAll)
</script>

<style scoped>
.admin-page {
  min-height: 100vh;
  background: #f8fafc;
  color: #0f172a;
  padding: 24px;
}

.topbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
}

h1 {
  font-size: 24px;
  line-height: 1.2;
  margin: 0 0 6px;
}

h2 {
  font-size: 16px;
  margin: 0;
}

p {
  color: #64748b;
  font-size: 14px;
  margin: 0;
}

.chat-link,
button {
  border: 1px solid #cbd5e1;
  background: #fff;
  color: #0f172a;
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 13px;
  text-decoration: none;
  cursor: pointer;
}

button:disabled {
  color: #94a3b8;
  cursor: not-allowed;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 20px;
}

.stat-card {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 14px;
}

.stat-card span {
  display: block;
  color: #64748b;
  font-size: 12px;
  margin-bottom: 8px;
}

.stat-card strong {
  font-size: 24px;
}

.content-grid {
  display: grid;
  grid-template-columns: 340px minmax(0, 1fr);
  gap: 16px;
}

.sessions-panel,
.messages-panel {
  grid-column: span 1;
}

.panel {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  min-height: 480px;
  overflow: hidden;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px;
  border-bottom: 1px solid #e2e8f0;
}

.user-row {
  width: 100%;
  display: flex;
  justify-content: space-between;
  gap: 12px;
  border: 0;
  border-bottom: 1px solid #f1f5f9;
  border-radius: 0;
  padding: 12px 14px;
  text-align: left;
}

.session-row {
  width: 100%;
  display: flex;
  justify-content: space-between;
  gap: 12px;
  border: 0;
  border-bottom: 1px solid #f1f5f9;
  border-radius: 0;
  padding: 12px 14px;
  text-align: left;
}

.session-row.active {
  background: #eff6ff;
}

.user-row.active {
  background: #eff6ff;
}

.user-row strong,
.meeting-row strong,
.session-row strong {
  display: block;
  font-size: 14px;
  margin-bottom: 4px;
}

.user-row span,
.meeting-row span,
.session-row span {
  color: #64748b;
  font-size: 12px;
}

.user-counts,
.meeting-meta,
.session-time {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  white-space: nowrap;
}

.meeting-list {
  max-height: calc(100vh - 260px);
  overflow-y: auto;
}

.message-list {
  max-height: 520px;
  overflow-y: auto;
}

.message-row {
  padding: 12px 14px;
  border-bottom: 1px solid #f1f5f9;
}

.message-row.assistant {
  background: #f8fafc;
}

.message-meta {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 6px;
}

.message-meta strong {
  font-size: 13px;
}

.message-meta span {
  color: #94a3b8;
  font-size: 12px;
}

.message-row p {
  color: #0f172a;
  line-height: 1.6;
  white-space: pre-wrap;
}

.tool-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.tool-list span {
  background: #dbeafe;
  color: #1d4ed8;
  border-radius: 999px;
  font-size: 12px;
  padding: 2px 8px;
}

.danger {
  border-color: #fecaca;
  color: #b91c1c;
}

.meeting-row {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 14px;
  border-bottom: 1px solid #f1f5f9;
}

.tag {
  border-radius: 999px;
  padding: 2px 8px;
}

.tag.done {
  background: #dcfce7;
  color: #15803d;
}

.tag.pending {
  background: #f1f5f9;
  color: #64748b;
}

.empty,
.error {
  padding: 24px 14px;
  color: #64748b;
  font-size: 14px;
}

.error {
  color: #b91c1c;
}

@media (max-width: 900px) {
  .stats-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .content-grid {
    grid-template-columns: 1fr;
  }
}
</style>
