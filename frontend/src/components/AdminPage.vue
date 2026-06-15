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
            :disabled="deletingSession"
            @click="removeSelectedSession"
          >
            {{ deletingSession ? '删除中' : '删除会话' }}
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

      <div class="panel session-memory-panel">
        <div class="panel-head session-memory-head">
          <div>
            <h2>会话记忆</h2>
            <span>{{ selectedSessionId ? '当前会话摘要' : '未选择会话' }}</span>
          </div>
          <button v-if="selectedSessionId" @click="loadSessionSummary" :disabled="loadingSessionSummary">
            {{ loadingSessionSummary ? '刷新中' : '刷新' }}
          </button>
        </div>

        <div v-if="!selectedSessionId" class="empty">
          选择一个会话后查看 Session Memory。
        </div>
        <div v-else-if="!sessionSummary && !loadingSessionSummary" class="empty">
          该会话还没有生成摘要。达到摘要阈值后会自动生成。
        </div>
        <div v-else-if="sessionSummary" class="session-summary">
          <div class="summary-meta">
            <span>{{ sessionSummary.user_id || '全局' }}</span>
            <span>{{ sessionSummary.message_count }} 条消息</span>
            <span>{{ sessionSummary.updated_at }}</span>
          </div>
          <p>{{ sessionSummary.summary }}</p>
        </div>
      </div>

      <div class="panel tasks-panel">
        <div class="panel-head task-head">
          <div>
            <h2>复杂任务</h2>
            <span>{{ selectedUserId || '全局' }} · {{ tasks.length }} 个</span>
          </div>
          <button @click="loadTasks" :disabled="loadingTasks">
            {{ loadingTasks ? '刷新中' : '刷新' }}
          </button>
          <button @click="recoverTasks" :disabled="recoveringTasks">
            {{ recoveringTasks ? '恢复中' : '恢复' }}
          </button>
        </div>

        <div class="task-create">
          <select v-model="taskType">
            <option value="topic_analysis">主题分析</option>
            <option value="weekly_report">周报素材</option>
            <option value="memory_build">构建长期记忆</option>
          </select>
          <input
            v-model="taskQuestion"
            placeholder="创建跨会议主题分析任务"
            @keyup.enter="createTask"
          />
          <button :disabled="creatingTask || !taskQuestion.trim()" @click="createTask">
            {{ creatingTask ? '创建中' : '创建' }}
          </button>
        </div>

        <div v-if="tasks.length === 0 && !loadingTasks" class="empty">
          暂无复杂任务。
        </div>

        <div class="task-list">
          <button
            v-for="task in tasks"
            :key="task.task_id"
            :class="['task-row', { active: task.task_id === selectedTaskId }]"
            @click="selectTask(task.task_id)"
          >
            <div>
              <strong>{{ task.question }}</strong>
              <span>{{ task.task_type || 'task' }} · step {{ task.current_step_index || 0 }}</span>
            </div>
            <div class="task-status-block">
              <span :class="['task-status', task.status]">{{ task.status }}</span>
              <span>{{ task.updated_at }}</span>
            </div>
          </button>
        </div>
      </div>

      <div class="panel task-steps-panel">
        <div class="panel-head">
          <h2>任务步骤</h2>
          <button
            v-if="selectedTask && !['completed', 'failed', 'canceled'].includes(selectedTask.status)"
            class="danger"
            @click="cancelTask"
          >
            取消任务
          </button>
          <button
            v-if="selectedTask && ['failed', 'interrupted', 'canceled'].includes(selectedTask.status)"
            @click="retryTask"
          >
            重试任务
          </button>
        </div>

        <div v-if="!selectedTaskId" class="empty">
          选择一个复杂任务后查看步骤。
        </div>
        <div v-else class="task-detail">
          <div v-if="selectedTask?.final_answer" class="task-final">
            <strong>最终结果</strong>
            <p>{{ selectedTask.final_answer }}</p>
          </div>
          <div v-if="selectedTask?.error" class="error">
            {{ selectedTask.error }}
          </div>
          <div class="step-list">
            <div v-for="step in taskSteps" :key="step.step_id" class="step-row">
              <div class="step-head">
                <strong>{{ step.step_index }}. {{ step.title }}</strong>
                <span :class="['task-status', step.status]">{{ step.status }}</span>
              </div>
              <p v-if="step.result">{{ step.result }}</p>
              <p v-if="step.error" class="step-error">{{ step.error }}</p>
            </div>
          </div>
          <div class="event-list">
            <h3>任务事件</h3>
            <div v-if="taskEvents.length === 0" class="empty compact">暂无事件。</div>
            <div v-for="event in taskEvents" :key="event.id" class="event-row">
              <span>{{ event.id }}</span>
              <strong>{{ event.event_type }}</strong>
              <em>{{ event.created_at }}</em>
              <pre>{{ formatEventPayload(event.payload) }}</pre>
            </div>
          </div>
        </div>
      </div>

      <div class="panel memories-panel">
        <div class="panel-head memory-head">
          <div>
            <h2>长期记忆</h2>
            <span>{{ selectedUserId || '全局' }} · {{ memories.length }} 条</span>
          </div>
          <button @click="loadMemories" :disabled="loadingMemories">
            {{ loadingMemories ? '刷新中' : '刷新' }}
          </button>
        </div>

        <div class="memory-filters">
          <input
            v-model="memoryQuery"
            placeholder="搜索 subject / content"
            @keyup.enter="loadMemories"
          />
          <label>
            <input v-model="includeInactiveMemories" type="checkbox" @change="loadMemories" />
            包含非 active
          </label>
        </div>

        <div v-if="memories.length === 0 && !loadingMemories" class="empty">
          暂无长期记忆。
        </div>

        <div class="memory-list">
          <div v-for="memory in memories" :key="memory.memory_id" class="memory-row">
            <div class="memory-meta">
              <span class="memory-kind">{{ memory.scope }}/{{ memory.memory_type }}</span>
              <span :class="['memory-status', memory.status]">{{ memory.status }}</span>
              <span>trust {{ formatTrust(memory.trust_score) }}</span>
            </div>
            <strong>{{ memory.subject || '未命名主题' }}</strong>
            <p>{{ memory.content }}</p>
            <div class="memory-foot">
              <span>{{ memory.source_type || 'unknown' }}</span>
              <span>{{ memory.updated_at || memory.created_at }}</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  cancelAgentTask,
  createAgentTask,
  getAgentTaskEvents,
  deleteSession,
  getAgentTaskSteps,
  getAgentTasks,
  getMemories,
  getSessionMessages,
  getSessionSummary,
  getSessions,
  getStats,
  getUsers,
  getUserMeetings,
  openAgentTaskEventStream,
  recoverAgentTasks,
  retryAgentTask,
} from '../api/agent.js'

const stats = ref(null)
const users = ref([])
const meetings = ref([])
const sessions = ref([])
const sessionMessages = ref([])
const sessionSummary = ref(null)
const memories = ref([])
const tasks = ref([])
const taskSteps = ref([])
const taskEvents = ref([])
const selectedTask = ref(null)
const selectedUserId = ref('')
const selectedSessionId = ref('')
const selectedTaskId = ref('')
const loading = ref(false)
const loadingMeetings = ref(false)
const loadingSessions = ref(false)
const loadingSessionSummary = ref(false)
const loadingMemories = ref(false)
const loadingTasks = ref(false)
const deletingSession = ref(false)
const creatingTask = ref(false)
const recoveringTasks = ref(false)
const memoryQuery = ref('')
const includeInactiveMemories = ref(false)
const taskQuestion = ref('')
const taskType = ref('topic_analysis')
const error = ref('')

let taskEventSource = null

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
    { label: '会话摘要', value: s.session_summaries },
    { label: '长期记忆', value: s.memories },
    { label: '复杂任务', value: s.agent_tasks },
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

function formatTrust(value) {
  return Number(value || 0).toFixed(2)
}

async function loadAll() {
  loading.value = true
  error.value = ''
  try {
    const [statsData, usersData] = await Promise.all([getStats(), getUsers()])
    stats.value = statsData
    users.value = usersData
    await Promise.all([loadSessions(), loadMemories(), loadTasks()])
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
  await Promise.all([loadMemories(), loadTasks()])
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

async function loadTasks() {
  loadingTasks.value = true
  try {
    tasks.value = await getAgentTasks({
      userId: selectedUserId.value,
      limit: 80,
    })
    if (selectedTaskId.value) {
      selectedTask.value = tasks.value.find((t) => t.task_id === selectedTaskId.value) || selectedTask.value
    }
  } catch (e) {
    error.value = `加载复杂任务失败：${e.message}`
  } finally {
    loadingTasks.value = false
  }
}

async function selectTask(taskId) {
  closeTaskEventStream()
  selectedTaskId.value = taskId
  selectedTask.value = tasks.value.find((t) => t.task_id === taskId) || null
  taskSteps.value = []
  taskEvents.value = []
  try {
    taskSteps.value = await getAgentTaskSteps(taskId)
    taskEvents.value = await getAgentTaskEvents(taskId)
    openTaskEventStream(taskId)
  } catch (e) {
    error.value = `加载任务步骤失败：${e.message}`
  }
}

async function createTask() {
  const question = taskQuestion.value.trim()
  if (!question || creatingTask.value) return
  creatingTask.value = true
  error.value = ''
  try {
    const task = await createAgentTask({
      question,
      userId: selectedUserId.value,
      taskType: taskType.value,
    })
    taskQuestion.value = ''
    tasks.value = [task, ...tasks.value]
    selectedTaskId.value = task.task_id
    selectedTask.value = task
    taskSteps.value = await getAgentTaskSteps(task.task_id)
    taskEvents.value = await getAgentTaskEvents(task.task_id)
    openTaskEventStream(task.task_id)
    await refreshStats()
  } catch (e) {
    error.value = e.message
  } finally {
    creatingTask.value = false
  }
}

async function retryTask() {
  if (!selectedTaskId.value) return
  try {
    selectedTask.value = await retryAgentTask(selectedTaskId.value)
    await loadTasks()
    await selectTask(selectedTaskId.value)
  } catch (e) {
    error.value = e.message
  }
}

async function recoverTasks() {
  recoveringTasks.value = true
  try {
    await recoverAgentTasks()
    await loadTasks()
  } catch (e) {
    error.value = e.message
  } finally {
    recoveringTasks.value = false
  }
}

function formatEventPayload(payload) {
  if (!payload || Object.keys(payload).length === 0) return ''
  return JSON.stringify(payload, null, 2)
}

function closeTaskEventStream() {
  if (taskEventSource) {
    taskEventSource.close()
    taskEventSource = null
  }
}

function openTaskEventStream(taskId) {
  closeTaskEventStream()
  const lastId = taskEvents.value.reduce((max, event) => Math.max(max, Number(event.id || 0)), 0)
  taskEventSource = openAgentTaskEventStream(taskId, lastId)
  taskEventSource.onmessage = async (message) => {
    try {
      const data = JSON.parse(message.data)
      if (data.type === 'event' && data.event) {
        if (!taskEvents.value.find((event) => event.id === data.event.id)) {
          taskEvents.value.push(data.event)
        }
        await Promise.allSettled([
          getAgentTaskSteps(taskId).then((steps) => {
            taskSteps.value = steps
          }),
          loadTasks(),
        ])
      } else if (data.type === 'done') {
        selectedTask.value = data.task
        await Promise.allSettled([
          getAgentTaskSteps(taskId).then((steps) => {
            taskSteps.value = steps
          }),
          loadTasks(),
        ])
        closeTaskEventStream()
      }
    } catch {
      // Ignore malformed SSE payloads; the next event or refresh repairs state.
    }
  }
  taskEventSource.onerror = () => {
    closeTaskEventStream()
  }
}

async function cancelTask() {
  if (!selectedTaskId.value) return
  const taskId = selectedTaskId.value
  try {
    selectedTask.value = await cancelAgentTask(taskId)
    await loadTasks()
    await selectTask(taskId)
  } catch (e) {
    error.value = e.message
  }
}

async function loadMemories() {
  loadingMemories.value = true
  try {
    memories.value = await getMemories({
      userId: selectedUserId.value,
      query: memoryQuery.value.trim(),
      includeInactive: includeInactiveMemories.value,
      limit: 80,
    })
  } catch (e) {
    error.value = `加载长期记忆失败：${e.message}`
  } finally {
    loadingMemories.value = false
  }
}

async function selectSession(sessionId) {
  selectedSessionId.value = sessionId
  sessionSummary.value = null
  const [data] = await Promise.all([getSessionMessages(sessionId), loadSessionSummary(sessionId)])
  sessionMessages.value = data?.messages || []
}

async function loadSessionSummary(sessionId = selectedSessionId.value) {
  if (!sessionId) return
  loadingSessionSummary.value = true
  try {
    sessionSummary.value = await getSessionSummary(sessionId)
  } catch (e) {
    error.value = `加载会话记忆失败：${e.message}`
  } finally {
    loadingSessionSummary.value = false
  }
}

async function removeSelectedSession() {
  if (!selectedSessionId.value) return
  const sessionId = selectedSessionId.value
  const hadSummary = Boolean(sessionSummary.value)
  deletingSession.value = true
  error.value = ''
  try {
    await deleteSession(sessionId)
    sessions.value = sessions.value.filter((s) => s.session_id !== sessionId)
    if (stats.value?.chat_sessions) {
      stats.value = {
        ...stats.value,
        chat_sessions: Math.max(Number(stats.value.chat_sessions) - 1, 0),
      }
      if (hadSummary && stats.value.session_summaries) {
        stats.value.session_summaries = Math.max(Number(stats.value.session_summaries) - 1, 0)
      }
    }
    selectedSessionId.value = ''
    sessionMessages.value = []
    sessionSummary.value = null
    await Promise.allSettled([loadSessions(), refreshStats()])
  } catch (e) {
    error.value = e.message
  } finally {
    deletingSession.value = false
  }
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
onBeforeUnmount(closeTaskEventStream)
</script>

<style scoped>
.admin-page {
  height: 100vh;
  background: #f8fafc;
  color: #0f172a;
  padding: 24px;
  overflow-y: auto;
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
  grid-template-columns: repeat(5, minmax(0, 1fr));
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
  grid-template-rows: minmax(0, 1fr) minmax(0, 1fr);
  gap: 16px;
  min-height: 0;
}

.sessions-panel,
.messages-panel,
.session-memory-panel,
.tasks-panel,
.task-steps-panel,
.memories-panel {
  grid-column: span 1;
}

.panel {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  min-height: 360px;
  max-height: min(640px, calc(100vh - 220px));
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.panel-head {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px;
  border-bottom: 1px solid #e2e8f0;
}

.users-panel,
.meetings-panel,
.sessions-panel,
.messages-panel,
.session-memory-panel,
.tasks-panel,
.task-steps-panel,
.memories-panel {
  min-width: 0;
}

.users-panel > .user-row,
.sessions-panel > .session-row {
  flex: 0 0 auto;
}

.users-panel,
.sessions-panel {
  overflow-y: auto;
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
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
}

.message-list {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
}

.memory-head span {
  display: block;
  color: #64748b;
  font-size: 12px;
  margin-top: 4px;
}

.session-memory-head span {
  display: block;
  color: #64748b;
  font-size: 12px;
  margin-top: 4px;
}

.task-head span {
  display: block;
  color: #64748b;
  font-size: 12px;
  margin-top: 4px;
}

.task-create {
  display: flex;
  gap: 8px;
  padding: 10px 14px;
  border-bottom: 1px solid #e2e8f0;
}

.task-create select {
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 13px;
  background: #fff;
}

.task-create input {
  flex: 1;
  min-width: 0;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 13px;
}

.task-list,
.task-detail {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
}

.task-row {
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

.task-row.active {
  background: #eff6ff;
}

.task-row > div:first-child {
  min-width: 0;
}

.task-row strong {
  display: block;
  font-size: 14px;
  margin-bottom: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.task-row span {
  color: #64748b;
  font-size: 12px;
}

.task-status-block {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  white-space: nowrap;
}

.task-status {
  border-radius: 999px;
  padding: 2px 8px;
  background: #f1f5f9;
  color: #475569;
  font-size: 12px;
}

.task-status.running {
  background: #dbeafe;
  color: #1d4ed8;
}

.task-status.completed {
  background: #dcfce7;
  color: #15803d;
}

.task-status.failed,
.task-status.interrupted,
.task-status.canceled {
  background: #fee2e2;
  color: #b91c1c;
}

.task-status.pending {
  background: #fef3c7;
  color: #92400e;
}

.task-final {
  padding: 14px;
  border-bottom: 1px solid #e2e8f0;
}

.task-final strong {
  display: block;
  margin-bottom: 8px;
}

.task-final p {
  color: #0f172a;
  line-height: 1.65;
  white-space: pre-wrap;
}

.step-row {
  padding: 12px 14px;
  border-bottom: 1px solid #f1f5f9;
}

.step-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.step-head strong {
  font-size: 14px;
}

.step-row p {
  color: #334155;
  line-height: 1.55;
  max-height: 180px;
  overflow-y: auto;
  white-space: pre-wrap;
}

.step-error {
  color: #b91c1c !important;
}

.event-list {
  border-top: 1px solid #e2e8f0;
}

.event-list h3 {
  font-size: 14px;
  padding: 12px 14px 0;
}

.event-row {
  padding: 10px 14px;
  border-bottom: 1px solid #f1f5f9;
}

.event-row span,
.event-row em {
  color: #64748b;
  font-size: 12px;
  font-style: normal;
  margin-right: 8px;
}

.event-row strong {
  color: #0f172a;
  font-size: 13px;
}

.event-row pre {
  margin-top: 6px;
  white-space: pre-wrap;
  word-break: break-word;
  color: #334155;
  font-size: 12px;
}

.compact {
  padding-top: 10px;
  padding-bottom: 10px;
}

.session-summary {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding: 14px;
}

.session-summary p {
  color: #0f172a;
  line-height: 1.65;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.summary-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 10px;
}

.summary-meta span {
  background: #f1f5f9;
  border-radius: 999px;
  color: #475569;
  font-size: 12px;
  padding: 2px 8px;
}

.memory-filters {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-bottom: 1px solid #e2e8f0;
}

.memory-filters input[type='text'],
.memory-filters input:not([type]) {
  flex: 1;
}

.memory-filters input:first-child {
  flex: 1;
  min-width: 0;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 13px;
}

.memory-filters label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #475569;
  font-size: 12px;
  white-space: nowrap;
}

.memory-list {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
}

.memory-row {
  padding: 12px 14px;
  border-bottom: 1px solid #f1f5f9;
}

.memory-row strong {
  display: block;
  color: #0f172a;
  font-size: 14px;
  margin: 6px 0;
  overflow-wrap: anywhere;
}

.memory-row p {
  color: #334155;
  line-height: 1.55;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.memory-meta,
.memory-foot {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  color: #64748b;
  font-size: 12px;
}

.memory-kind,
.memory-status {
  border-radius: 999px;
  padding: 2px 8px;
  background: #f1f5f9;
}

.memory-status.active {
  background: #dcfce7;
  color: #15803d;
}

.memory-status.deprecated,
.memory-status.deleted,
.memory-status.expired {
  background: #fee2e2;
  color: #b91c1c;
}

.memory-foot {
  margin-top: 8px;
  justify-content: space-between;
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
  min-width: 0;
}

.meeting-row > div:first-child,
.session-row > div:first-child,
.user-row > div:first-child {
  min-width: 0;
}

.meeting-row strong,
.session-row strong,
.user-row strong {
  overflow: hidden;
  text-overflow: ellipsis;
}

.meeting-row strong,
.meeting-row span {
  overflow-wrap: anywhere;
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
    grid-template-rows: none;
  }

  .panel {
    max-height: none;
  }
}
</style>
