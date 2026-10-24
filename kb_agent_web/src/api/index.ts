import axios from 'axios'
import { ElMessage } from 'element-plus'

export const http = axios.create({
  baseURL: '/api',
  timeout: 120000,
})

http.interceptors.request.use((config) => {
  const token = localStorage.getItem('kb_token')
  if (token) {
    config.headers = config.headers || {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

http.interceptors.response.use(
  (response) => {
    const body = response.data
    if (body && typeof body.code === 'number' && body.code !== 0) {
      ElMessage.error(body.message || '请求失败')
      return Promise.reject(new Error(body.message))
    }
    return body?.data !== undefined ? body.data : body
  },
  (error) => {
    const status = error.response?.status
    const message = error.response?.data?.message || error.message || '网络异常'
    if (status === 401) {
      localStorage.removeItem('kb_token')
      localStorage.removeItem('kb_user')
      if (!location.hash.includes('/login')) location.hash = '#/login'
    }
    ElMessage.error(message)
    return Promise.reject(error)
  },
)

export interface ChatResult {
  answer: string
  citations: Array<{ unit_id: string; title: string; snippet?: string; ref_index?: number }>
  unauthorized_count: number
  cached: boolean
  session_id: string
  response_time_ms: number
}

/**
 * SSE 流式问答：浏览器端用 fetch 读取 ReadableStream 并解析 event/data。
 */
export async function streamChat(
  question: string,
  sessionId: string | null,
  handlers: {
    onDelta?: (text: string) => void
    onCitations?: (citations: any[]) => void
    onWarning?: (count: number) => void
    onDone?: (payload: any) => void
    onError?: (message: string) => void
  },
): Promise<void> {
  const token = localStorage.getItem('kb_token')
  const resp = await fetch('/api/ai/chat/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ question, session_id: sessionId }),
  })

  if (!resp.ok || !resp.body) {
    let message = `请求失败（${resp.status}）`
    try {
      const data = await resp.json()
      message = data.message || message
    } catch {
      /* ignore */
    }
    handlers.onError?.(message)
    return
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  const dispatch = (rawEvent: string) => {
    let event = 'message'
    const dataLines: string[] = []
    for (const line of rawEvent.split('\n')) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
    }
    if (!dataLines.length) return
    let payload: any = {}
    try {
      payload = JSON.parse(dataLines.join('\n'))
    } catch {
      return
    }
    if (event === 'message_delta') handlers.onDelta?.(payload.delta_text || '')
    else if (event === 'citations') handlers.onCitations?.(payload.citations || [])
    else if (event === 'permission_warning') handlers.onWarning?.(payload.unauthorized_count || 0)
    else if (event === 'done') handlers.onDone?.(payload)
    else if (event === 'error') handlers.onError?.(payload.message || '生成失败')
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let idx = buffer.indexOf('\n\n')
    while (idx !== -1) {
      dispatch(buffer.slice(0, idx))
      buffer = buffer.slice(idx + 2)
      idx = buffer.indexOf('\n\n')
    }
  }
  if (buffer.trim()) dispatch(buffer)
}

export const api = {
  login: (username: string, password: string) => http.post('/auth/login', { username, password }),
  me: () => http.get('/auth/me'),

  departments: () => http.get('/org/departments'),
  departmentTree: () => http.get('/org/departments/tree'),
  departmentMembers: (id: string) => http.get(`/org/departments/${id}/members`),
  updateDepartment: (id: string, data: any) => http.put(`/org/departments/${id}`, data),
  roles: () => http.get('/org/roles'),
  users: (params?: any) => http.get('/org/users', { params }),
  permissionCodes: () => http.get('/org/permission-codes'),
  createDepartment: (data: any) => http.post('/org/departments', data),
  createRole: (data: any) => http.post('/org/roles', data),
  updateRole: (id: string, data: any) => http.put(`/org/roles/${id}`, data),
  assignRolePermissions: (id: string, permissions: string[]) =>
    http.post(`/org/roles/${id}/permissions`, { permissions }),
  createUser: (data: any) => http.post('/org/users', data),
  updateUser: (id: string, data: any) => http.put(`/org/users/${id}`, data),
  resetPassword: (id: string) => http.post(`/org/users/${id}/password/reset`),

  units: (params?: any) => http.get('/knowledge/units', { params }),
  unit: (id: string) => http.get(`/knowledge/units/${id}`),
  updateUnit: (id: string, data: any) => http.put(`/knowledge/units/${id}`, data),
  setUnitPermissions: (id: string, targets: any[]) =>
    http.post(`/knowledge/units/${id}/permissions`, { targets }),
  deleteUnits: (unit_ids: string[]) => http.request({ url: '/knowledge/units', method: 'delete', data: { unit_ids } }),
  checkPermissions: (unit_ids: string[]) => http.post('/knowledge/check-permissions', { unit_ids }),

  chat: (question: string, session_id?: string) => http.post('/ai/chat', { question, session_id }),
  sessions: (limit = 20) => http.get('/ai/sessions', { params: { limit } }),
  sessionMessages: (id: string) => http.get(`/ai/sessions/${id}/messages`),
  adminChat: (message: string, history: any[], session_id?: string) =>
    http.post('/agent/admin/chat', { message, history, session_id }),

  dashboardMetrics: () => http.get('/dashboard/metrics'),
  topQuestions: (limit = 10) => http.get('/dashboard/rankings/questions', { params: { limit } }),
  topUnits: (limit = 10) => http.get('/dashboard/rankings/units', { params: { limit } }),
  tokenStats: (days = 14, granularity: 'day' | 'week' = 'day') =>
    http.get('/dashboard/stats/tokens', { params: { days, granularity } }),
  responseTimeStats: (days = 14) => http.get('/dashboard/stats/response-time', { params: { days } }),

  faqs: (params?: any) => http.get('/settlement/faqs', { params }),
  faqRecommendations: () => http.get('/settlement/faqs/recommendations'),
  reviewFaq: (id: string, action: 'approve' | 'reject', edited_answer?: string) =>
    http.post(`/settlement/faqs/${id}/review`, { action, edited_answer }),
  knowledgeGaps: () => http.get('/settlement/knowledge-gaps'),
  createUnitFromGap: (gapId: string, data: any) =>
    http.post(`/settlement/knowledge-gaps/${gapId}/create-unit`, data),
  recentLogs: (limit = 20) => http.get('/settlement/logs', { params: { limit } }),
}
