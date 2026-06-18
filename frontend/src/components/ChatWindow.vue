<template>
  <div class="chat-window">
    <!-- 消息列表 -->
    <div class="messages" ref="messagesEl" @scroll="updateAutoScrollState">
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
            <button
              type="button"
              class="tool-toggle"
              @click="toggleTools(msg)"
            >
              <span class="tool-toggle-left">
                <span :class="['tool-toggle-dot', toolSummaryStatus(msg.toolCalls)]" aria-hidden="true"></span>
                <span>{{ toolSummaryText(msg.toolCalls) }}</span>
              </span>
              <span class="tool-toggle-chevron">{{ msg.toolsExpanded ? '收起' : '展开' }}</span>
            </button>

            <div v-if="msg.toolsExpanded" class="tool-steps">
              <div
                v-for="tc in msg.toolCalls"
                :key="tc.tool + tc.status"
                :class="['tool-step', tc.status]"
              >
                <span class="tool-status-dot" aria-hidden="true"></span>
                <span class="tool-copy">
                  <span class="tool-title">{{ toolMeta(tc.tool).title }}</span>
                  <span class="tool-desc">{{ toolDetailText(tc) }}</span>
                </span>
              </div>
            </div>
          </div>

          <!-- 回答内容 -->
          <div class="content markdown-body" v-html="renderContent(msg.content)"></div>
          <div v-if="msg.sources?.length" class="source-list">
            <div class="source-list-title">引用来源</div>
            <button
              v-if="msg.sources.length > SOURCE_PREVIEW_LIMIT"
              type="button"
              class="source-toggle"
              @click="toggleSources(msg)"
            >
              {{ msg.sourcesExpanded ? '收起' : `查看全部 ${msg.sources.length} 条` }}
            </button>
            <div
              v-for="source in visibleSources(msg)"
              :key="source.source_id + source.chunk_id + source.quote"
              class="source-item"
            >
              <span class="source-id">[{{ source.source_id }}]</span>
              <span class="source-main">
                <span class="source-title">《{{ source.meeting_title || '未命名会议' }}》</span>
                <span v-if="source.create_time" class="source-meta">{{ shortDate(source.create_time) }}</span>
                <span v-if="source.speaker" class="source-meta">发言人：{{ source.speaker }}</span>
                <span v-if="source.quote" class="source-quote">{{ source.quote }}</span>
              </span>
            </div>
          </div>
          <span v-if="msg.streaming" class="cursor">▌</span>
        </div>
      </div>

      <!-- 加载中占位 -->
      <div v-if="loading && messages.length === 0" class="message assistant">
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
      <button class="send-btn" @click="send" :disabled="loading || !input.trim()">
        {{ loading ? '…' : '发送' }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'

const props = defineProps({
  sessionId: { type: String, default: null },
  userId: { type: String, default: '' },
  messages: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
})

const emit = defineEmits(['send'])

const input = ref('')
const messagesEl = ref(null)
const inputEl = ref(null)
const shouldAutoScroll = ref(true)
let scrollFrame = null
const SOURCE_PREVIEW_LIMIT = 3

// 工具状态展示：后端 Agent 每次调用工具时，前端把它渲染成执行步骤。
const TOOL_META = {
  search_meetings: {
    title: '检索会议原文',
    description: '从转写片段中查找相关讨论',
  },
  multi_search_meetings: {
    title: '多角度检索会议原文',
    description: '用多个语义 query 融合召回相关讨论',
  },
  get_action_items: {
    title: '整理待办事项',
    description: '读取负责人、截止时间和任务内容',
  },
  get_decisions: {
    title: '提取决策记录',
    description: '查找会议中已经确定的结论',
  },
  get_risks: {
    title: '排查风险项',
    description: '汇总会议里提到的问题和阻塞',
  },
  get_meeting_summary: {
    title: '读取会议摘要',
    description: '获取主题、摘要和核心要点',
  },
  list_meetings: {
    title: '列出相关会议',
    description: '按时间筛选可参考的会议记录',
  },
  get_meeting_detail: {
    title: '展开会议详情',
    description: '读取摘要、结构化记忆和原文片段',
  },
  search_by_time_range: {
    title: '按时间范围检索',
    description: '在指定日期范围内查找会议内容',
  },
  get_topic_history: {
    title: '追踪主题历史',
    description: '按时间线梳理相关讨论',
  },
  generate_weekly_report: {
    title: '生成周报素材',
    description: '汇总会议摘要、待办、决策和风险',
  },
  web_search: {
    title: '联网补充信息',
    description: '搜索会议库之外的外部资料',
  },
}
const toolMeta = (name) => TOOL_META[name] || {
  title: name,
  description: '执行内部工具调用',
}
const toolStatusText = (status) => {
  if (status === 'blocked') return '已停止继续检索'
  if (status === 'failed') return '调用失败'
  if (status === 'done') return '已完成'
  return '正在执行'
}
const toolSummaryStatus = (toolCalls) => {
  if (toolCalls.some((tc) => tc.status === 'failed')) return 'failed'
  if (toolCalls.some((tc) => tc.status === 'running')) return 'running'
  if (toolCalls.some((tc) => tc.status === 'blocked')) return 'blocked'
  return 'done'
}
const toolSummaryText = (toolCalls) => {
  const running = toolCalls.filter((tc) => tc.status === 'running').length
  const failed = toolCalls.filter((tc) => tc.status === 'failed').length
  const blocked = toolCalls.filter((tc) => tc.status === 'blocked').length
  if (running) return `正在执行 ${running} 个步骤，已记录 ${toolCalls.length} 个工具调用`
  if (failed) return `执行了 ${toolCalls.length} 个步骤，其中 ${failed} 个失败`
  if (blocked) return `执行了 ${toolCalls.length} 个步骤，已停止 ${blocked} 个继续检索请求`
  return `已执行 ${toolCalls.length} 个步骤`
}

function compactValue(value, maxLength = 72) {
  if (value === null || value === undefined || value === '') return ''
  const text = String(value)
  return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text
}

function shortDate(value) {
  return String(value || '').slice(0, 10)
}

function toolArgumentSummary(toolCall) {
  const args = toolCall.arguments || {}
  switch (toolCall.tool) {
    case 'search_meetings':
    case 'web_search':
      return compactValue(args.query) ? `查询：${compactValue(args.query)}` : ''
    case 'multi_search_meetings': {
      const queries = Array.isArray(args.queries) ? args.queries.filter(Boolean) : []
      const text = queries.slice(0, 3).join('；')
      const suffix = queries.length > 3 ? ` 等 ${queries.length} 个查询` : ''
      return text ? `查询：${compactValue(text + suffix)}` : ''
    }
    case 'get_action_items':
    case 'get_decisions':
    case 'get_risks':
      return compactValue(args.keyword) ? `关键词：${compactValue(args.keyword)}` : ''
    case 'list_meetings':
      return args.limit ? `数量：${args.limit}` : ''
    case 'get_meeting_summary':
    case 'get_meeting_detail':
      return compactValue(args.note_id, 36) ? `会议ID：${compactValue(args.note_id, 36)}` : ''
    case 'search_by_time_range': {
      const range = [args.start || '最早', args.end || '最新'].join(' 至 ')
      const query = compactValue(args.query)
      return query ? `范围：${range}；查询：${query}` : `范围：${range}`
    }
    case 'get_topic_history':
      return compactValue(args.topic) ? `主题：${compactValue(args.topic)}` : ''
    case 'generate_weekly_report':
      return `范围：${args.start || '最早'} 至 ${args.end || '最新'}`
    default:
      return ''
  }
}

function toolDetailText(toolCall) {
  const parts = [
    toolStatusText(toolCall.status),
    toolMeta(toolCall.tool).description,
  ]
  const args = toolArgumentSummary(toolCall)
  if (args) parts.push(args)
  return parts.join(' · ')
}

function toggleTools(msg) {
  msg.toolsExpanded = !msg.toolsExpanded
}

function visibleSources(msg) {
  const sources = msg.sources || []
  return msg.sourcesExpanded ? sources : sources.slice(0, SOURCE_PREVIEW_LIMIT)
}

function toggleSources(msg) {
  msg.sourcesExpanded = !msg.sourcesExpanded
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function safeUrl(url) {
  const trimmed = url.trim()
  if (/^(https?:\/\/|mailto:)/i.test(trimmed)) return escapeHtml(trimmed)
  if (/^[#/]/.test(trimmed)) return escapeHtml(trimmed)
  return '#'
}

function renderInlineMarkdown(value) {
  return escapeHtml(value)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, label, url) => {
      return `<a href="${safeUrl(url)}" target="_blank" rel="noreferrer">${label}</a>`
    })
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/__([^_]+)__/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
    .replace(/(^|[^_])_([^_\n]+)_/g, '$1<em>$2</em>')
}

function closeList(state, html) {
  if (state.listType) {
    html.push(`</${state.listType}>`)
    state.listType = ''
  }
}

function flushParagraph(state, html) {
  if (state.paragraph.length) {
    html.push(`<p>${renderInlineMarkdown(state.paragraph.join(' '))}</p>`)
    state.paragraph = []
  }
}

function isTableSeparatorCell(value) {
  return /^:?-{3,}:?$/.test(value.trim())
}

function isTableSeparatorLine(line) {
  const cells = splitTableRow(line)
  return cells.length > 0 && cells.every(isTableSeparatorCell)
}

function splitTableRow(line) {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim())
}

function tableCellClass(header) {
  const normalized = header.trim().toLowerCase()
  if (['序号', '编号', 'no', 'id'].includes(normalized)) return 'col-index'
  if (normalized.includes('标题') || normalized.includes('title')) return 'col-title'
  if (normalized.includes('日期') || normalized.includes('date')) return 'col-date'
  if (normalized.includes('时长') || normalized.includes('duration')) return 'col-duration'
  if (normalized.includes('note_id') || normalized.includes('note id')) return 'col-note-id'
  return ''
}

function renderTable(rows) {
  if (rows.length < 2 || !isTableSeparatorLine(rows[1])) return ''
  const header = splitTableRow(rows[0])
  const bodyRows = rows
    .slice(2)
    .filter((row) => row.trim() && !isTableSeparatorLine(row))
    .map(splitTableRow)

  const classes = header.map(tableCellClass)
  const headHtml = header
    .map((cell, index) => `<th class="${classes[index]}">${renderInlineMarkdown(cell)}</th>`)
    .join('')
  const bodyHtml = bodyRows
    .map((row) => {
      const cells = header
        .map((_, index) => `<td class="${classes[index]}">${renderInlineMarkdown(row[index] || '')}</td>`)
        .join('')
      return `<tr>${cells}</tr>`
    })
    .join('')

  return `<div class="table-wrap"><table><thead><tr>${headHtml}</tr></thead><tbody>${bodyHtml}</tbody></table></div>`
}

function normalizeCompactTableLine(line) {
  if ((line.match(/\|/g) || []).length < 6) return line

  const cells = splitTableRow(line).filter(Boolean)
  const separatorStart = cells.findIndex((cell, index) => {
    return index > 0 && isTableSeparatorCell(cell) && isTableSeparatorCell(cells[index + 1] || '')
  })

  if (separatorStart <= 0) return line

  const columnCount = separatorStart
  const header = cells.slice(0, columnCount)
  const separators = cells.slice(separatorStart, separatorStart + columnCount)
  const body = cells.slice(separatorStart + columnCount)
  if (separators.length !== columnCount || body.length < columnCount) return line

  const lines = [
    `| ${header.join(' | ')} |`,
    `| ${separators.join(' | ')} |`,
  ]

  for (let index = 0; index < body.length; index += columnCount) {
    const row = body.slice(index, index + columnCount)
    if (row.length === columnCount) lines.push(`| ${row.join(' | ')} |`)
  }

  return lines.join('\n')
}

function normalizeHeadingBreaks(text) {
  return String(text).replace(/([^\n])(\s*)(#{1,6}\s+)(?=\S)/g, (match, before, space, heading) => {
    if (before === '#' || before === '`') return match
    const separator = /[。！？；.!?;:：）)]$/.test(before) ? '\n\n' : '\n'
    return `${before}${separator}${heading}`
  })
}

function normalizeMarkdown(text) {
  return normalizeHeadingBreaks(text)
    .replace(/\r\n?/g, '\n')
    .split('\n')
    .map(normalizeCompactTableLine)
    .join('\n')
}

// 支持常用 Markdown：标题、列表、表格、分割线、引用、代码块、链接、粗体、斜体、行内代码。
function renderContent(text) {
  if (!text) return ''

  const lines = normalizeMarkdown(text).split('\n')
  const html = []
  const state = { paragraph: [], listType: '', inCode: false, codeLines: [] }

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index]
    const fence = line.match(/^```/)
    if (fence) {
      if (state.inCode) {
        html.push(`<pre><code>${escapeHtml(state.codeLines.join('\n'))}</code></pre>`)
        state.inCode = false
        state.codeLines = []
      } else {
        flushParagraph(state, html)
        closeList(state, html)
        state.inCode = true
      }
      continue
    }

    if (state.inCode) {
      state.codeLines.push(line)
      continue
    }

    if (!line.trim()) {
      flushParagraph(state, html)
      closeList(state, html)
      continue
    }

    if (/^\s{0,3}(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      flushParagraph(state, html)
      closeList(state, html)
      html.push('<hr>')
      continue
    }

    if (line.includes('|') && isTableSeparatorLine(lines[index + 1] || '')) {
      flushParagraph(state, html)
      closeList(state, html)
      const tableLines = [line, lines[index + 1]]
      index += 2
      while (index < lines.length && lines[index].includes('|') && lines[index].trim()) {
        tableLines.push(lines[index])
        index += 1
      }
      index -= 1
      html.push(renderTable(tableLines))
      continue
    }

    const heading = line.match(/^(#{1,6})\s+(.+)$/)
    if (heading) {
      flushParagraph(state, html)
      closeList(state, html)
      const level = heading[1].length
      html.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`)
      continue
    }

    const quote = line.match(/^>\s?(.+)$/)
    if (quote) {
      flushParagraph(state, html)
      closeList(state, html)
      html.push(`<blockquote>${renderInlineMarkdown(quote[1])}</blockquote>`)
      continue
    }

    const unordered = line.match(/^\s*[-*+]\s+(.+)$/)
    const ordered = line.match(/^\s*\d+\.\s+(.+)$/)
    if (unordered || ordered) {
      flushParagraph(state, html)
      const nextType = unordered ? 'ul' : 'ol'
      if (state.listType !== nextType) {
        closeList(state, html)
        html.push(`<${nextType}>`)
        state.listType = nextType
      }
      html.push(`<li>${renderInlineMarkdown((unordered || ordered)[1])}</li>`)
      continue
    }

    closeList(state, html)
    state.paragraph.push(line.trim())
  }

  if (state.inCode) html.push(`<pre><code>${escapeHtml(state.codeLines.join('\n'))}</code></pre>`)
  flushParagraph(state, html)
  closeList(state, html)
  return html.join('')
}

function scrollToBottom() {
  if (scrollFrame) cancelAnimationFrame(scrollFrame)
  scrollFrame = requestAnimationFrame(() => {
    if (messagesEl.value)
      messagesEl.value.scrollTop = messagesEl.value.scrollHeight
    scrollFrame = null
  })
}

function updateAutoScrollState() {
  const el = messagesEl.value
  if (!el) return
  const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight
  shouldAutoScroll.value = distanceToBottom < 96
}

function scrollToBottomIfNeeded() {
  if (shouldAutoScroll.value) scrollToBottom()
}

watch(() => props.messages.length, scrollToBottomIfNeeded)
watch(
  () => props.messages.map((msg) => `${msg.id}:${msg.content.length}`).join('|'),
  scrollToBottomIfNeeded,
)

async function send() {
  const q = input.value.trim()
  if (!q || props.loading) return
  input.value = ''
  shouldAutoScroll.value = true
  emit('send', q)
  nextTick(() => inputEl.value?.focus())
}
</script>

<style scoped>
.chat-window {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  min-width: 0;
  background: rgba(248, 250, 252, 0.72);
}

.messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 28px clamp(18px, 4vw, 52px);
  display: flex;
  flex-direction: column;
  gap: 18px;
  scroll-behavior: auto;
}

.empty-hint {
  margin: auto;
  text-align: center;
  color: #475569;
  padding: 34px 38px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.72);
  box-shadow: 0 18px 48px rgba(15, 23, 42, 0.08);
  backdrop-filter: blur(18px);
}
.empty-hint p:first-child {
  font-size: 20px;
  font-weight: 700;
  color: #0f172a;
}
.empty-hint .sub { font-size: 13px; margin-top: 8px; }

.message {
  display: flex;
  contain: layout paint;
}
.message.user  { justify-content: flex-end; }
.message.assistant { justify-content: flex-start; }

.bubble {
  max-width: min(980px, 82%);
  padding: 13px 16px;
  border-radius: 16px;
  font-size: 14px;
  line-height: 1.7;
  word-break: break-word;
  box-shadow: 0 14px 34px rgba(15, 23, 42, 0.08);
  isolation: isolate;
}

.user-bubble {
  background: linear-gradient(135deg, #2563eb, #0ea5a3);
  color: #fff;
  border-bottom-right-radius: 6px;
}

.assistant-bubble {
  max-width: min(980px, 88%);
  padding: 2px 0;
  background: transparent;
  color: #172033;
  border: 0;
  border-radius: 0;
  box-shadow: none;
}

.tool-calls {
  display: flex;
  flex-direction: column;
  gap: 0;
  margin-bottom: 14px;
  border: 1px solid rgba(226, 232, 240, 0.72);
  border-radius: 10px;
  background: rgba(248, 250, 252, 0.55);
  overflow: hidden;
}

.tool-toggle {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 11px;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: #475569;
  cursor: pointer;
  transition: background 0.18s, border-color 0.18s;
}

.tool-toggle:hover {
  background: rgba(241, 245, 249, 0.9);
}

.tool-toggle-left {
  display: inline-flex;
  min-width: 0;
  align-items: center;
  gap: 9px;
  font-size: 12px;
  font-weight: 650;
}

.tool-toggle-dot {
  width: 8px;
  height: 8px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: #10b981;
  box-shadow: 0 0 0 4px rgba(16, 185, 129, 0.12);
}

.tool-toggle-dot.running {
  background: #2563eb;
  box-shadow: 0 0 0 4px rgba(37, 99, 235, 0.12);
  animation: pulse-dot 1.2s ease-in-out infinite;
}

.tool-toggle-dot.failed {
  background: #ef4444;
  box-shadow: 0 0 0 4px rgba(239, 68, 68, 0.12);
}

.tool-toggle-dot.blocked {
  background: #f59e0b;
  box-shadow: 0 0 0 4px rgba(245, 158, 11, 0.14);
}

.tool-toggle-chevron {
  flex: 0 0 auto;
  color: #64748b;
  font-size: 12px;
}

.tool-steps {
  display: flex;
  flex-direction: column;
  gap: 0;
  border-top: 1px solid rgba(226, 232, 240, 0.72);
}

.tool-step {
  display: grid;
  grid-template-columns: 10px minmax(0, 1fr);
  gap: 10px;
  align-items: start;
  padding: 9px 11px;
  border: 0;
  border-top: 1px solid rgba(226, 232, 240, 0.55);
  background: transparent;
  transition: background 0.16s, border-color 0.16s;
}

.tool-step:first-child {
  border-top: 0;
}

.tool-step:hover {
  background: rgba(241, 245, 249, 0.9);
  border-color: rgba(203, 213, 225, 0.9);
}

.tool-status-dot {
  width: 8px;
  height: 8px;
  margin-top: 6px;
  border-radius: 50%;
  background: #2563eb;
  box-shadow: 0 0 0 4px rgba(37, 99, 235, 0.12);
}

.tool-step.running .tool-status-dot {
  animation: pulse-dot 1.2s ease-in-out infinite;
}

.tool-step.done .tool-status-dot {
  background: #10b981;
  box-shadow: 0 0 0 4px rgba(16, 185, 129, 0.12);
}

.tool-step.failed .tool-status-dot {
  background: #ef4444;
  box-shadow: 0 0 0 4px rgba(239, 68, 68, 0.12);
}

.tool-step.blocked .tool-status-dot {
  background: #f59e0b;
  box-shadow: 0 0 0 4px rgba(245, 158, 11, 0.14);
}

.tool-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.tool-title {
  color: #0f172a;
  font-size: 13px;
  font-weight: 700;
}

.tool-desc {
  color: #64748b;
  font-size: 12px;
  line-height: 1.45;
}

@keyframes pulse-dot {
  0%, 100% {
    opacity: 0.72;
    transform: scale(0.92);
  }
  50% {
    opacity: 1;
    transform: scale(1.1);
  }
}

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
  flex-shrink: 0;
  gap: 10px;
  padding: 18px clamp(18px, 4vw, 56px) 22px;
  border-top: 1px solid rgba(226, 232, 240, 0.76);
  background: rgba(255, 255, 255, 0.58);
  backdrop-filter: blur(22px);
}

textarea {
  flex: 1;
  min-height: 44px;
  padding: 12px 14px;
  border: 1px solid rgba(203, 213, 225, 0.9);
  border-radius: 12px;
  resize: none;
  font-size: 14px;
  font-family: inherit;
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s, background 0.2s;
  max-height: 120px;
  background: rgba(255, 255, 255, 0.86);
  color: #0f172a;
}
textarea:focus {
  border-color: #2563eb;
  box-shadow: 0 0 0 4px rgba(37, 99, 235, 0.12);
}
textarea:disabled { background: #f9fafb; }

.send-btn {
  min-width: 72px;
  padding: 0 20px;
  background: #1f2937;
  color: #fff;
  border: none;
  border-radius: 12px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s, transform 0.2s, box-shadow 0.2s;
  white-space: nowrap;
  box-shadow: 0 10px 24px rgba(17, 24, 39, 0.18);
}
.send-btn:hover:not(:disabled) {
  background: #0f766e;
  transform: translateY(-1px);
}
.send-btn:disabled {
  background: #cbd5e1;
  color: #64748b;
  cursor: not-allowed;
  box-shadow: none;
}

.markdown-body :deep(p) { margin: 0 0 10px; }
.markdown-body :deep(p:last-child) { margin-bottom: 0; }
.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4),
.markdown-body :deep(h5),
.markdown-body :deep(h6) {
  margin: 14px 0 8px;
  color: #0f172a;
  line-height: 1.3;
  font-weight: 750;
}
.markdown-body :deep(h1:first-child),
.markdown-body :deep(h2:first-child),
.markdown-body :deep(h3:first-child) { margin-top: 0; }
.markdown-body :deep(h1) { font-size: 22px; }
.markdown-body :deep(h2) { font-size: 19px; }
.markdown-body :deep(h3) { font-size: 16px; }
.markdown-body :deep(h4),
.markdown-body :deep(h5),
.markdown-body :deep(h6) { font-size: 14px; }
.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  margin: 8px 0 10px 22px;
  padding: 0;
}
.markdown-body :deep(li) { margin: 4px 0; }
.markdown-body :deep(blockquote) {
  margin: 10px 0;
  padding: 8px 12px;
  border-left: 3px solid #14b8a6;
  background: #f0fdfa;
  color: #334155;
}
.markdown-body :deep(hr) {
  height: 1px;
  margin: 16px 0;
  border: 0;
  background: linear-gradient(90deg, transparent, #cbd5e1, transparent);
}
.markdown-body :deep(.table-wrap) {
  max-width: 100%;
  margin: 12px 0;
  overflow-x: auto;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #fff;
}
.markdown-body :deep(table) {
  width: max-content;
  min-width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  table-layout: auto;
}
.markdown-body :deep(th),
.markdown-body :deep(td) {
  padding: 9px 12px;
  border-bottom: 1px solid #e2e8f0;
  text-align: left;
  vertical-align: top;
}
.markdown-body :deep(th) {
  background: #f8fafc;
  color: #334155;
  font-weight: 700;
}
.markdown-body :deep(th.col-index),
.markdown-body :deep(td.col-index) {
  width: 1%;
  min-width: 46px;
  text-align: center;
  color: #64748b;
  white-space: nowrap;
}
.markdown-body :deep(th.col-title),
.markdown-body :deep(td.col-title) {
  min-width: 180px;
  max-width: 360px;
  white-space: normal;
}
.markdown-body :deep(th.col-date),
.markdown-body :deep(td.col-date),
.markdown-body :deep(th.col-duration),
.markdown-body :deep(td.col-duration) {
  width: 1%;
  white-space: nowrap;
}
.markdown-body :deep(th.col-note-id),
.markdown-body :deep(td.col-note-id) {
  width: 1%;
  white-space: nowrap;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
}
.markdown-body :deep(tr:last-child td) { border-bottom: 0; }
.markdown-body :deep(pre) {
  margin: 12px 0;
  padding: 12px 14px;
  overflow-x: auto;
  border-radius: 8px;
  background: #0f172a;
  color: #e2e8f0;
  font-size: 13px;
  line-height: 1.55;
}
.markdown-body :deep(code) {
  padding: 2px 5px;
  border-radius: 5px;
  background: #eef2f7;
  color: #0f172a;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.92em;
}
.markdown-body :deep(pre code) {
  padding: 0;
  background: transparent;
  color: inherit;
}
.markdown-body :deep(a) {
  color: #0f766e;
  font-weight: 600;
  text-decoration: none;
}
.markdown-body :deep(a:hover) { text-decoration: underline; }

.source-list {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid rgba(203, 213, 225, 0.72);
}

.source-list-title {
  margin-bottom: 8px;
  color: #334155;
  font-size: 12px;
  font-weight: 750;
}

.source-toggle {
  display: inline-flex;
  width: fit-content;
  margin: -2px 0 6px;
  padding: 0;
  border: 0;
  background: transparent;
  color: #0f766e;
  cursor: pointer;
  font-size: 12px;
  font-weight: 650;
}

.source-toggle:hover {
  color: #115e59;
  text-decoration: underline;
}

.source-item {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 8px;
  padding: 8px 0;
  color: #475569;
  font-size: 12px;
  line-height: 1.55;
}

.source-item + .source-item {
  border-top: 1px dashed rgba(203, 213, 225, 0.72);
}

.source-id {
  color: #0f766e;
  font-weight: 750;
  white-space: nowrap;
}

.source-main {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  gap: 4px 8px;
}

.source-title {
  color: #0f172a;
  font-weight: 650;
}

.source-meta {
  color: #64748b;
}

.source-quote {
  flex-basis: 100%;
  display: -webkit-box;
  overflow: hidden;
  color: #64748b;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

@media (max-width: 720px) {
  .messages { padding: 20px 14px; }
  .bubble { max-width: 92%; }
  .input-area { padding: 12px; }
  .send-btn { min-width: 64px; padding: 0 14px; }
}
</style>
