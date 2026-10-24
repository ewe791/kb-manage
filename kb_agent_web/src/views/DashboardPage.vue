<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api'

const metrics = ref<any>({})
const questions = ref<any[]>([])
const units = ref<any[]>([])
const trend = ref<any[]>([])
const rtStats = ref<any>({ buckets: [], total: 0 })
const logs = ref<any[]>([])
const loading = ref(false)
const granularity = ref<'day' | 'week'>('day')

const maxQuestion = computed(() => Math.max(1, ...questions.value.map((q) => q.count)))
const maxUnit = computed(() => Math.max(1, ...units.value.map((u) => u.count)))
const maxToken = computed(() =>
  Math.max(1, ...trend.value.map((t) => t.prompt_tokens + t.completion_tokens)),
)

function shortDate(date: string) {
  return date.slice(5)
}

const maxBucket = computed(() =>
  Math.max(1, ...(rtStats.value?.buckets || []).map((b: any) => b.count)),
)

async function reloadTrend() {
  const t: any = await api.tokenStats(14, granularity.value)
  trend.value = t || []
}

async function load() {
  loading.value = true
  try {
    const [m, q, u, t, rt, l]: any = await Promise.all([
      api.dashboardMetrics(),
      api.topQuestions(8),
      api.topUnits(8),
      api.tokenStats(14, granularity.value),
      api.responseTimeStats(14),
      api.recentLogs(8),
    ])
    metrics.value = m || {}
    questions.value = q || []
    units.value = u || []
    trend.value = t || []
    rtStats.value = rt || { buckets: [], total: 0 }
    logs.value = l || []
  } finally {
    loading.value = false
  }
}

onMounted(load)

function fmt(n: number | undefined) {
  if (n === undefined || n === null) return '0'
  return n >= 10000 ? `${(n / 10000).toFixed(1)}w` : `${n}`
}
</script>

<template>
  <div v-loading="loading">
    <div class="page-head">
      <h2>运营看板</h2>
      <p>访问、Token 消耗、常见问题与最常访问知识单元</p>
      <div style="flex: 1"></div>
      <el-button size="small" @click="load">刷新</el-button>
    </div>

    <div class="metric-grid">
      <div class="card metric accent">
        <div class="label"><span>总访问量</span><span>↗</span></div>
        <div class="value">{{ fmt(metrics.total_access) }}</div>
        <div class="delta">累计问答次数</div>
      </div>
      <div class="card metric">
        <div class="label"><span>活跃用户</span><span>UV</span></div>
        <div class="value">{{ fmt(metrics.uv) }}</div>
        <div class="delta">去重提问用户</div>
      </div>
      <div class="card metric">
        <div class="label"><span>知识单元</span><span>KB</span></div>
        <div class="value">{{ fmt(metrics.unit_total) }}</div>
        <div class="delta">状态为启用</div>
      </div>
      <div class="card metric">
        <div class="label"><span>Token 总量</span><span>∑</span></div>
        <div class="value">{{ fmt(metrics.total_tokens) }}</div>
        <div class="delta">prompt + completion</div>
      </div>
      <div class="card metric">
        <div class="label"><span>平均响应</span><span>ms</span></div>
        <div class="value">{{ Math.round(metrics.avg_response_ms || 0) }}</div>
        <div class="delta">FAQ 命中 {{ Math.round((metrics.faq_hit_rate || 0) * 100) }}%</div>
      </div>
    </div>

    <div class="split-2">
      <div class="card card-pad">
        <div style="display: flex; align-items: center; margin-bottom: 8px">
          <div>
            <p class="section-title">每日 Token 与耗时趋势</p>
            <p class="section-sub">近 14 天，按{{ granularity === 'day' ? '日' : '周' }}聚合</p>
          </div>
          <div style="flex: 1"></div>
          <el-radio-group v-model="granularity" size="small" style="margin-right: 14px" @change="reloadTrend">
            <el-radio-button value="day">按日</el-radio-button>
            <el-radio-button value="week">按周</el-radio-button>
          </el-radio-group>
          <div class="legend">
            <span><i style="background: #4f5dff"></i>completion</span>
            <span><i style="background: #ccd2ff"></i>prompt</span>
          </div>
        </div>
        <div v-if="!trend.length" class="empty-hint">暂无数据，先去问答工作台提几个问题</div>
        <div v-else class="trend">
          <div v-for="item in trend" :key="item.date" class="trend-col">
            <div class="trend-stack">
              <i
                class="hot"
                :style="{ height: `${(item.completion_tokens / maxToken) * 100}%` }"
                :title="`completion ${item.completion_tokens}`"
              ></i>
              <i
                :style="{ height: `${(item.prompt_tokens / maxToken) * 100}%` }"
                :title="`prompt ${item.prompt_tokens}`"
              ></i>
            </div>
            <div class="trend-label">{{ shortDate(item.date) }}</div>
          </div>
        </div>
        <div v-if="trend.length" style="margin-top: 14px; font-size: 12px; color: #6b7280">
          平均响应耗时：
          <b style="color: #0f1729">{{ trend[trend.length - 1]?.avg_response_ms }} ms</b>
          ·  当日访问 {{ trend[trend.length - 1]?.access_count }} 次
        </div>
      </div>

      <div class="card card-pad">
        <p class="section-title">常见问题 TOP</p>
        <p class="section-sub" style="margin-bottom: 8px">按问题前 20 字符聚类计数</p>
        <div v-if="!questions.length" class="empty-hint">暂无提问记录</div>
        <div v-for="(q, idx) in questions" :key="idx" class="rank-row">
          <span class="rank-idx">{{ idx + 1 }}</span>
          <span class="name" :title="q.question">{{ q.question }}</span>
          <div class="bar"><i :style="{ width: `${(q.count / maxQuestion) * 100}%` }"></i></div>
          <span style="width: 28px; text-align: right; color: #6b7280; font-size: 12px">{{ q.count }}</span>
        </div>
      </div>
    </div>

    <div class="split-2" style="margin-top: 16px">
      <div class="card card-pad">
        <p class="section-title">最常访问知识单元</p>
        <p class="section-sub" style="margin-bottom: 8px">按授权命中次数展开统计</p>
        <div v-if="!units.length" class="empty-hint">暂无访问记录</div>
        <div v-for="(u, idx) in units" :key="u.unit_id" class="rank-row">
          <span class="rank-idx">{{ idx + 1 }}</span>
          <span class="name" :title="u.title">{{ u.title }}</span>
          <div class="bar"><i :style="{ width: `${(u.count / maxUnit) * 100}%`, background: 'linear-gradient(90deg,#34d3c0,#10b3a3)' }"></i></div>
          <span style="width: 28px; text-align: right; color: #6b7280; font-size: 12px">{{ u.count }}</span>
        </div>
      </div>

      <div class="card card-pad">
        <p class="section-title">响应时间分布</p>
        <p class="section-sub" style="margin-bottom: 10px">
          近 14 天 · 共 {{ rtStats.total || 0 }} 次问答 · 平均 {{ rtStats.avg_ms || 0 }} ms
        </p>
        <div v-if="!rtStats.total" class="empty-hint">暂无耗时数据</div>
        <div v-else>
          <div v-for="b in rtStats.buckets" :key="b.label" class="rank-row" style="padding: 7px 0">
            <span style="width: 84px; font-size: 12px; color: #475467">{{ b.label }}</span>
            <div class="bar" style="flex: 1; width: auto">
              <i
                :style="{
                  width: `${(b.count / maxBucket) * 100}%`,
                  background: 'linear-gradient(90deg,#8f9bff,#4f5dff)',
                }"
              ></i>
            </div>
            <span style="width: 32px; text-align: right; font-size: 12px; color: #6b7280">{{ b.count }}</span>
          </div>
          <div style="display: flex; gap: 10px; margin-top: 12px">
            <span class="pill blue">P50 {{ rtStats.p50_ms }} ms</span>
            <span class="pill">P95 {{ rtStats.p95_ms }} ms</span>
            <span class="pill green">FAQ 命中率 {{ Math.round((metrics.faq_hit_rate || 0) * 100) }}%</span>
          </div>
        </div>
      </div>
    </div>

    <div class="card card-pad" style="margin-top: 16px">
        <p class="section-title">最近访问日志</p>
        <p class="section-sub" style="margin-bottom: 10px">字段完整落库，供沉淀与审计复用</p>
        <div v-if="!logs.length" class="empty-hint">暂无日志</div>
        <div v-for="log in logs" :key="log.id" style="padding: 9px 0; border-bottom: 1px dashed #e6e8ef">
          <div style="display: flex; gap: 8px; align-items: center">
            <span class="pill" :class="log.unauthorized_unit_ids.length ? 'red' : 'green'">
              {{ log.unauthorized_unit_ids.length ? `缺 ${log.unauthorized_unit_ids.length}` : '已授权' }}
            </span>
            <span style="font-size: 12.5px; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">
              {{ log.question }}
            </span>
            <span style="font-size: 11.5px; color: #98a2b3">{{ log.total_tokens }} tok</span>
          </div>
          <div class="mono" style="color: #98a2b3; margin-top: 3px">
            召回 {{ log.recalled_unit_ids.length }} · 授权 {{ log.authorized_unit_ids.length }} ·
            {{ log.response_time_ms }}ms
          </div>
        </div>
    </div>
  </div>
</template>
