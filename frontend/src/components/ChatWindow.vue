<template>
  <div class="chat-window">
    <!-- 消息列表 -->
    <div class="messages" ref="messagesEl">
      <div v-if="messages.length === 0" class="empty-hint">
        <p>向 MeetAgent 提问吧</p>
        <p class="sub">例如：最近有哪些风险？ / 我有哪些待办事项？</p>
      </div>

      <div
        v-for="msg in messages"
        :key="msg.id"
        :class="['message', msg.role]"
      >
        <!-- 用户消息 -->
        <div v-if="msg.role === 'user'" class="bubble user-bubble">
          {{ msg.content }}
        </div>

        <!-- 助手消息 -->
        <div v-else class="bubble assistant-bubble">
          <!-- 工具调用状态 -->
          <div v-if="msg.toolCalls.length" class="tool-calls">
            <span
              v-for="tc in msg.toolCalls"
              :key="tc.tool + tc.status"
              :class="['tool-badge', tc.status]"
            >
              <span class="tool-icon">{{ tc.status === 'done' ? '✓' : '⟳' }}</span>
              {{ toolLabel(tc.tool) }}
            </span>
          </div>

          <!-- 回答内容 -->
          <div class="content" v-html="renderContent(msg.content)"></div>
          <span v-if="msg.streaming" class="cursor">▌</span>
        </div>
      </div>

      <!-- 加载中占位 -->
      <div v-if="loading && !streamingMsg" class="message assistant">
        <div class="bubble assistant-bubble loading">
          <span class="dot"></span><span class="dot"></span><span class="dot"></span>
        </div>
      </div>
    </div>

    <!-- 输入区 -->
    <div class="input-area">
      <textarea
        v-model="input"
        placeholder="输入问题，Enter 发送，Shift+Enter 换行"
        :disabled="loading"
        @keydown.enter.exact.prevent="send"
        rows="1"
        ref="inputEl"
      ></textarea>
      <button @click="send" :disabled="loading || !input.trim()">
        {{ loading ? '…' : '发送' }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'
import { streamChat } from '../api/agent.js'

const props = defineProps({
  sessionId: { type: String, default: null },
  userId: { type: String, default: '' },
  initialMessages: { type: Array, default: () => [] },
})

const emit = defineEmits(['session-created'])

const messages = ref([...props.initialMessages])
const input = ref('')
const loading = ref(false)
const streamingMsg = ref(null)
const messagesEl = ref(null)
const inputEl = ref(null)

let currentSessionId = props.sessionId

// 工具名称映射
const TOOL_LABELS = {
  search_meetings: '搜索会议原文',
  get_action_items: '查询待办事项',
  get_decisions: '查询决策记录',
  get_risks: '查询风险项',
  get_meeting_summary: '获取会议摘要',
  list_meetings: '列出会议清单',
}
const toolLabel = (name) => TOOL_LABELS[name] || name

// 简单 Markdown：换行和粗体
function renderContent(text) {
  if (!text) return ''
  return text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>')
}

function scrollToBottom() {
  nextTick(() => {
    if (messagesEl.value)
      messagesEl.value.scrollTop = messagesEl.value.scrollHeight
  })
}

watch(messages, scrollToBottom, { deep: true })

async function send() {
  const q = input.value.trim()
  if (!q || loading.value) return

  // 追加用户消息
  messages.value.push({ id: Date.now(), role: 'user', content: q, toolCalls: [] })
  input.value = ''
  loading.value = true

  // 助手消息占位
  const assistantMsg = {
    id: Date.now() + 1,
    role: 'assistant',
    content: '',
    toolCalls: [],
    streaming: true,
  }
  messages.value.push(assistantMsg)
  streamingMsg.value = assistantMsg

  try {
    for await (const event of streamChat({
      question: q,
      userId: props.userId,
      sessionId: currentSessionId,
    })) {
      if (event.type === 'session_id') {
        currentSessionId = event.session_id
        emit('session-created', event.session_id, q)

      } else if (event.type === 'tool_start') {
        assistantMsg.toolCalls.push({ tool: event.tool, status: 'running' })

      } else if (event.type === 'tool_done') {
        const tc = assistantMsg.toolCalls.find(t => t.tool === event.tool && t.status === 'running')
        if (tc) tc.status = 'done'

      } else if (event.type === 'token') {
        assistantMsg.content += event.content

      } else if (event.type === 'done') {
        assistantMsg.streaming = false

      } else if (event.type === 'error') {
        assistantMsg.content = `出错了：${event.message}`
        assistantMsg.streaming = false
      }
      scrollToBottom()
    }
  } catch (e) {
    assistantMsg.content = `网络错误：${e.message}`
    assistantMsg.streaming = false
  }

  streamingMsg.value = null
  loading.value = false
  nextTick(() => inputEl.value?.focus())
}
</script>

<style scoped>
.chat-window {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 24px 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.empty-hint {
  margin: auto;
  text-align: center;
  color: #999;
}
.empty-hint .sub { font-size: 13px; margin-top: 6px; }

.message { display: flex; }
.message.user  { justify-content: flex-end; }
.message.assistant { justify-content: flex-start; }

.bubble {
  max-width: 72%;
  padding: 12px 16px;
  border-radius: 16px;
  font-size: 14px;
  line-height: 1.6;
  word-break: break-word;
}

.user-bubble {
  background: #2563eb;
  color: #fff;
  border-bottom-right-radius: 4px;
}

.assistant-bubble {
  background: #f3f4f6;
  color: #111;
  border-bottom-left-radius: 4px;
}

.tool-calls {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}

.tool-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 12px;
  background: #dbeafe;
  color: #1d4ed8;
}
.tool-badge.done { background: #dcfce7; color: #15803d; }

.tool-icon { font-size: 11px; }

.cursor {
  display: inline-block;
  animation: blink 0.8s step-end infinite;
  color: #2563eb;
  margin-left: 2px;
}
@keyframes blink { 50% { opacity: 0; } }

.loading { display: flex; gap: 5px; align-items: center; padding: 14px 20px; }
.dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: #9ca3af;
  animation: bounce 1.2s infinite;
}
.dot:nth-child(2) { animation-delay: 0.2s; }
.dot:nth-child(3) { animation-delay: 0.4s; }
@keyframes bounce {
  0%, 80%, 100% { transform: translateY(0); }
  40% { transform: translateY(-6px); }
}

.input-area {
  display: flex;
  gap: 10px;
  padding: 16px;
  border-top: 1px solid #e5e7eb;
  background: #fff;
}

textarea {
  flex: 1;
  padding: 10px 14px;
  border: 1px solid #d1d5db;
  border-radius: 10px;
  resize: none;
  font-size: 14px;
  font-family: inherit;
  outline: none;
  transition: border-color 0.2s;
  max-height: 120px;
}
textarea:focus { border-color: #2563eb; }
textarea:disabled { background: #f9fafb; }

button {
  padding: 10px 20px;
  background: #2563eb;
  color: #fff;
  border: none;
  border-radius: 10px;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.2s;
  white-space: nowrap;
}
button:hover:not(:disabled) { background: #1d4ed8; }
button:disabled { background: #93c5fd; cursor: not-allowed; }
</style>
