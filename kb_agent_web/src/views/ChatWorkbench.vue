<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import MarkdownIt from 'markdown-it'
import { api, streamChat } from '@/api'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const md = new MarkdownIt({ html: false, linkify: true, breaks: true })

interface Citation {
  unit_id: string
  title: string
  snippet?: string
  ref_index?: number
}

interface Message {
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
  unauthorized?: number
  cached?: boolean
  ms?: number
  trace?: Array<{ tool: string; arguments?: any; ok: boolean; error?: string }>
  loading?: boolean
  error?: boolean
}

const mode = ref<'user' | 'admin'>(auth.hasPermission('knowledge:permission') ? 'admin' : 'user')
const canAdmin = computed(() => auth.hasPermission('knowledge:permission'))
const canUser = computed(() => auth.hasPermission('ai:access'))

const userMessages = ref<Message[]>([])
const adminMessages = ref<Message[]>([])
const input = ref('')
const sending = ref(false)
const sessionId = ref<string | null>(null)
const scrollRef = ref<HTMLElement | null>(null)
const citationDialog = ref(false)
const activeCitation = ref<Citation | null>(null)
const historyOpen = ref(false)
const historyLoading = ref(false)
const sessions = ref<any[]>([])

const userPrompts = [
  '差旅住宿标准是多少？',
  '年假有几天，可以跨年结转吗？',
  '加班调休的有效期是多久？',
  '如何申请远程办公？',
]
const adminPrompts = [
  '最近有什么没答上来的问题？',
  '列出当前所有知识单元和它们的权限',
  '把《产品使用手册》授权给财务部和市场部',
  '看一下待审核的 FAQ 推荐',
]

const currentMessages = computed(() =>
  mode.value === 'admin' ? adminMessages.value : userMessages.value,
)
const prompts = computed(() => (mode.value === 'admin' ? adminPrompts : userPrompts))
const placeholder = computed(() =>
  mode.value === 'admin'
    ? '告诉我要做什么，例如：把这份文档导入，只给财务部看'
    : '输入你的问题，回答将严格限定在你的权限范围内',
)

const tools = [
  { title: '导入知识', desc: '上传 / 导入文档并自动切片向量化', prompt: '帮我把一份文档导入知识库，分类为财务制度' },
  { title: '配置权限', desc: '按全局 / 部门 / 角色 / 人员授权', prompt: '列出所有知识单元，我要调整权限' },
  { title: '审核 FAQ', desc: '审核高频问答沉淀，发布后进入缓存', prompt: '看一下待审核的 FAQ 推荐' },
  { title: '知识缺口', desc: '定位没答上来的问题并补齐知识', prompt: '最近有什么没答上来的问题？按次数排序' },
]

function render(text: string) {
  return md.render(text || '')
}

/** 权限缺失说明已由红色警示条专门承载，正文中不重复展示 */
function displayContent(msg: Message) {
  let text = msg.content || ''
  if (msg.unauthorized) {
    text = text.replace(/\n*（另有\s*\d+\s*条相关知识您暂无访问权限）\s*$/, '')
  }
  return text
}

function scrollToBottom() {
  nextTick(() => {
    const el = scrollRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

watch(
  () => currentMessages.value.map((m) => m.content.length).join(','),
  () => scrollToBottom(),
)

onMounted(() => {
  if (!canUser.value) mode.value = 'admin'
})

function switchMode(next: 'user' | 'admin') {
  if (next === 'admin' && !canAdmin.value) return
  if (next === 'user' && !canUser.value) return
  mode.value = next
}

function openCitation(citation: Citation) {
  activeCitation.value = citation
  citationDialog.value = true
}

function usePrompt(text: string) {
  input.value = text
}

async function send() {
  const question = input.value.trim()
  if (!question || sending.value) return
  input.value = ''
  sending.value = true

  if (mode.value === 'user') {
    userMessages.value.push({ role: 'user', content: question })
    const assistant: Message = { role: 'assistant', content: '', loading: true }
    userMessages.value.push(assistant)
    scrollToBottom()
    await streamChat(question, sessionId.value, {
      onDelta: (text) => {
        assistant.content += text
        scrollToBottom()
      },
      onCitations: (citations) => {
        assistant.citations = citations
      },
      onWarning: (count) => {
        assistant.unauthorized = count
      },
      onDone: (payload) => {
        assistant.loading = false
        assistant.cached = !!payload?.cached
        assistant.ms = payload?.response_time_ms
        if (payload?.session_id) sessionId.value = payload.session_id
        sending.value = false
        scrollToBottom()
      },
      onError: (message) => {
        assistant.loading = false
        assistant.error = true
        assistant.content = message || '生成失败，请稍后重试'
        sending.value = false
      },
    })
    if (sending.value) {
      assistant.loading = false
      sending.value = false
    }
    return
  }

  adminMessages.value.push({ role: 'user', content: question })
  const assistant: Message = { role: 'assistant', content: '', loading: true }
  adminMessages.value.push(assistant)
  scrollToBottom()
  try {
    const history = adminMessages.value
      .slice(0, -2)
      .filter((m) => m.content && !m.loading)
      .slice(-8)
      .map((m) => ({ role: m.role, content: m.content }))
    const result: any = await api.adminChat(question, history, sessionId.value || undefined)
    assistant.content = result.answer || '（无输出）'
    assistant.trace = result.tool_trace || []
    assistant.loading = false
    if (result.session_id) sessionId.value = result.session_id
  } catch (error: any) {
    assistant.content = error?.message || '管理助手调用失败'
    assistant.error = true
    assistant.loading = false
  } finally {
    sending.value = false
    scrollToBottom()
  }
}

async function openHistory() {
  historyOpen.value = true
  historyLoading.value = true
  try {
    const data: any = await api.sessions(30)
    sessions.value = data || []
  } finally {
    historyLoading.value = false
  }
}

async function loadSession(item: any) {
  const data: any = await api.sessionMessages(item.session_id)
  sessionId.value = item.session_id
  const restored: Message[] = []
  for (const msg of data.messages || []) {
    restored.push({ role: 'user', content: msg.question })
    restored.push({
      role: 'assistant',
      content: msg.answer,
      citations: msg.citations || [],
      unauthorized: msg.unauthorized_count || 0,
    })
  }
  userMessages.value = restored
  historyOpen.value = false
  scrollToBottom()
}

function resetChat() {
  if (mode.value === 'admin') adminMessages.value = []
  else {
    userMessages.value = []
    sessionId.value = null
  }
}

function toolTitle(name: string) {
  const map: Record<string, string> = {
    import_knowledge: '导入知识',
    list_units: '查询单元',
    get_unit: '查看单元',
    update_unit: '更新单元',
    delete_units: '删除单元',
    set_unit_permissions: '配置权限',
    list_faq_recommendations: 'FAQ 推荐',
    review_faq: '审核 FAQ',
    list_knowledge_gaps: '知识缺口',
    get_dashboard_metrics: '看板指标',
  }
  return map[name] || name
}
</script>

<template>
  <div>
    <div class="page-head">
      <h2>{{ mode === 'admin' ? '管理助手' : '智能问答' }}</h2>
      <p>
        {{ mode === 'admin'
          ? '用自然语言完成导入、授权、审核与缺口排查'
          : '检索 → 鉴权 → 生成，权限由服务端硬编码裁决' }}
      </p>
      <div style="flex: 1"></div>
      <el-radio-group v-if="canAdmin && canUser" :model-value="mode" size="small" @update:model-value="switchMode">
        <el-radio-button value="user">知识问答</el-radio-button>
        <el-radio-button value="admin">管理助手</el-radio-button>
      </el-radio-group>
      <el-button v-if="mode === 'user'" size="small" @click="openHistory">历史会话</el-button>
      <el-button size="small" @click="resetChat">新会话</el-button>
    </div>

    <div class="workbench">
      <div class="chat-panel">
        <div ref="scrollRef" class="chat-scroll">
          <div v-if="!currentMessages.length" class="empty-state" style="padding: 26px 0 10px">
            <div
              style="
                width: 54px;
                height: 54px;
                border-radius: 16px;
                background: #eef0ff;
                color: #4f5dff;
                display: grid;
                place-items: center;
                font-size: 24px;
                margin-bottom: 14px;
              "
            >
              ◈
            </div>
            <h3 style="margin: 0 0 6px; font-size: 17px">
              {{ mode === 'admin' ? '今天要处理哪件事？' : `你好，${auth.user?.display_name || ''}` }}
            </h3>
            <p style="color: #6b7280; font-size: 13px; margin: 0 0 18px">
              {{
                mode === 'admin'
                  ? '我可以帮你导入文档、配置四维权限、审核 FAQ、查看知识缺口'
                  : '我的回答只会基于你有权访问的知识片段，并标注引用来源'
              }}
            </p>
            <div class="demo-row" style="justify-content: center">
              <div v-for="p in prompts" :key="p" class="demo-chip" @click="usePrompt(p)">{{ p }}</div>
            </div>
          </div>

          <div v-for="(msg, idx) in currentMessages" :key="idx" class="msg" :class="msg.role">
            <div class="who">{{ msg.role === 'user' ? (auth.user?.display_name || '我').slice(0, 1) : 'AI' }}</div>
            <div class="msg-body">
              <div class="bubble" :style="msg.user || msg.role === 'user' ? '' : ''">
                <div v-if="msg.role === 'user'" style="white-space: pre-wrap">{{ msg.content }}</div>
                <template v-else>
                  <div v-if="msg.loading && !msg.content" class="typing">
                    <span></span><span></span><span></span>
                  </div>
                  <div v-else class="md" v-html="render(displayContent(msg))"></div>

                  <div v-if="msg.trace?.length" class="trace">
                    <div class="trace-item" v-for="(t, i) in msg.trace" :key="i">
                      <span :class="t.ok ? 'ok' : 'fail'">{{ t.ok ? '●' : '×' }}</span>
                      <span>{{ toolTitle(t.tool) }}</span>
                      <span v-if="t.error" style="color: #b42318">— {{ t.error }}</span>
                    </div>
                  </div>

                  <div v-if="msg.citations?.length" class="citation-row">
                    <div
                      v-for="(c, i) in msg.citations"
                      :key="c.unit_id + i"
                      class="citation-chip"
                      @click="openCitation(c)"
                    >
                      <span>[{{ c.ref_index || i + 1 }}]</span>
                      <span>{{ c.title }}</span>
                    </div>
                  </div>

                  <div v-if="msg.unauthorized" class="warn-bar">
                    <span style="font-size: 14px; line-height: 1.2">⚠</span>
                    <div>
                      另有 {{ msg.unauthorized }} 条相关知识您暂无访问权限。如需查看，请联系知识管理员申请授权。
                    </div>
                  </div>

                  <div v-if="!msg.loading" class="meta-line">
                    <span v-if="msg.cached" class="pill green">FAQ 命中缓存</span>
                    <span v-if="msg.ms !== undefined && msg.ms !== null" class="pill">耗时 {{ msg.ms }} ms</span>
                    <span v-if="msg.error" class="pill red">请求失败</span>
                  </div>
                </template>
              </div>
            </div>
          </div>
        </div>

        <div class="composer">
          <el-input
            v-model="input"
            type="textarea"
            :rows="2"
            :placeholder="placeholder"
            :disabled="sending"
            @keydown.enter.exact.prevent="send"
          />
          <div class="composer-bar">
            <span class="tip">
              {{ mode === 'admin' ? 'Enter 发送 · 管理操作会真实写入数据库' : 'Enter 发送 · 回答带引用编号' }}
            </span>
            <div style="flex: 1"></div>
            <el-button type="primary" size="small" :loading="sending" @click="send">
              {{ mode === 'admin' ? '执行' : '提问' }}
            </el-button>
          </div>
        </div>
      </div>

      <aside class="side-tools">
        <div class="card card-pad" v-if="mode === 'admin'">
          <p class="section-title">管理工具速达</p>
          <p class="section-sub" style="margin-bottom: 14px">点击填入指令，或直接自然语言描述</p>
          <div style="display: flex; flex-direction: column; gap: 10px">
            <div v-for="tool in tools" :key="tool.title" class="tool-card" @click="usePrompt(tool.prompt)">
              <div class="tool-icon">◆</div>
              <div>
                <b>{{ tool.title }}</b>
                <span>{{ tool.desc }}</span>
              </div>
            </div>
          </div>
        </div>

        <div class="card card-pad" v-else>
          <p class="section-title">回答规则</p>
          <p class="section-sub">模型只拿到你被授权的片段</p>
          <div style="margin-top: 12px; display: flex; flex-direction: column; gap: 10px; font-size: 12.5px; color: #475467">
            <div>① 先查 FAQ 缓存，命中即返回（不调用模型）</div>
            <div>② 向量召回候选片段，去重保留最高分</div>
            <div>③ 服务端硬编码鉴权，未经授权直接剔除</div>
            <div>④ 仅用授权片段生成，末尾标注引用编号</div>
            <div>⑤ 全程写入访问日志，供看板与沉淀使用</div>
          </div>
        </div>

        <div class="card card-pad">
          <p class="section-title">我的访问范围</p>
          <p class="section-sub" style="margin-bottom: 10px">当前账号的角色与部门</p>
          <div style="display: flex; gap: 6px; flex-wrap: wrap">
            <span class="pill blue">{{ auth.user?.department_name || '未分配部门' }}</span>
            <span v-for="r in auth.roleLabels" :key="r" class="pill">{{ r }}</span>
          </div>
          <div style="margin-top: 14px; border-top: 1px dashed #e6e8ef; padding-top: 12px">
            <el-button text size="small" @click="router.push({ name: 'knowledge' })" v-if="auth.hasPermission('knowledge:read')">
              查看知识单元与权限 →
            </el-button>
          </div>
        </div>
      </aside>
    </div>

    <el-drawer v-model="historyOpen" title="历史会话" size="380px">
      <div v-loading="historyLoading">
        <div v-if="!sessions.length" class="empty-hint">还没有历史会话记录</div>
        <div
          v-for="item in sessions"
          :key="item.session_id"
          class="source-card"
          style="cursor: pointer"
          :style="item.session_id === sessionId ? 'border-color:#c9cfff;background:#f7f8ff' : ''"
          @click="loadSession(item)"
        >
          <div class="q" style="margin-bottom: 4px">{{ item.title }}</div>
          <div style="font-size: 11.5px; color: #98a2b3">
            {{ item.message_count }} 轮 · {{ (item.last_at || '').replace('T', ' ').slice(0, 16) }}
          </div>
          <div style="font-size: 12px; color: #6b7280; margin-top: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">
            最近：{{ item.last_question }}
          </div>
        </div>
      </div>
      <div style="margin-top: 12px; font-size: 11.5px; color: #98a2b3">
        仅展示当前账号自己的会话；历史答案沿用当时的权限结果。
      </div>
    </el-drawer>

    <el-dialog v-model="citationDialog" title="引用原文片段" width="620px">
      <template v-if="activeCitation">
        <div style="font-weight: 600; margin-bottom: 8px">{{ activeCitation.title }}</div>
        <div style="font-size: 13px; line-height: 1.9; color: #475467; white-space: pre-wrap">
          {{ activeCitation.snippet || '暂无片段内容' }}
        </div>
        <div class="mono" style="margin-top: 12px; color: #98a2b3">unit_id: {{ activeCitation.unit_id }}</div>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.typing {
  display: flex;
  gap: 4px;
  align-items: center;
  height: 20px;
}
.typing span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #b6bdf0;
  animation: blink 1.2s infinite ease-in-out;
}
.typing span:nth-child(2) {
  animation-delay: 0.15s;
}
.typing span:nth-child(3) {
  animation-delay: 0.3s;
}
@keyframes blink {
  0%,
  80%,
  100% {
    opacity: 0.3;
    transform: translateY(0);
  }
  40% {
    opacity: 1;
    transform: translateY(-2px);
  }
}
</style>
