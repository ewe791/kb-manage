<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '@/api'

const tab = ref('pending')
const pending = ref<any[]>([])
const published = ref<any[]>([])
const gaps = ref<any[]>([])
const loading = ref(false)

const reviewDialog = ref(false)
const current = ref<any>(null)
const editedAnswer = ref('')

const gapTotal = computed(() => gaps.value.reduce((sum, g) => sum + g.ask_count, 0))

const departments = ref<any[]>([])
const roles = ref<any[]>([])
const users = ref<any[]>([])

const gapDialog = ref(false)
const gapForm = reactive({ gap_id: '', title: '', content: '', category: '未分类' })
const gapTargets = ref<any[]>([])
const savingGap = ref(false)

async function load() {
  loading.value = true
  try {
    const [p, pub, g]: any = await Promise.all([
      api.faqRecommendations(),
      api.faqs({ status: 'published', page_size: 50 }),
      api.knowledgeGaps(),
    ])
    pending.value = p || []
    published.value = pub?.items || []
    gaps.value = g || []
  } finally {
    loading.value = false
  }
}

async function loadRefs() {
  const [d, r, u]: any = await Promise.all([api.departments(), api.roles(), api.users({ page_size: 100 })])
  departments.value = d || []
  roles.value = r || []
  users.value = u?.items || []
}

onMounted(() => {
  load()
  loadRefs().catch(() => {})
})

function openGapUnit(gap: any) {
  gapForm.gap_id = gap.id
  gapForm.title = gap.question_pattern
  gapForm.category = '未分类'
  gapForm.content = `# ${gap.question_pattern}\n\n## 标准说明\n（请补充制度依据与适用条件）\n\n## 具体规则\n1. \n2. \n\n## 常见问题\n- ${(gap.sample_questions || []).slice(0, 3).join('\n- ') || '（补充用户常见问法）'}\n`
  gapTargets.value = []
  gapDialog.value = true
}

async function saveGapUnit() {
  if (!gapForm.title || gapForm.content.trim().length < 10) {
    ElMessage.warning('请填写标题与正文内容')
    return
  }
  savingGap.value = true
  try {
    await api.createUnitFromGap(gapForm.gap_id, {
      title: gapForm.title,
      content: gapForm.content,
      category: gapForm.category || '未分类',
      targets: gapTargets.value,
    })
    ElMessage.success('知识单元已创建，缺口已标记解决')
    gapDialog.value = false
    load()
  } finally {
    savingGap.value = false
  }
}

function openReview(faq: any) {
  current.value = faq
  editedAnswer.value = faq.answer
  reviewDialog.value = true
}

async function review(action: 'approve' | 'reject') {
  if (!current.value) return
  await api.reviewFaq(current.value.id, action, editedAnswer.value)
  ElMessage.success(action === 'approve' ? '已发布并写入缓存' : '已驳回')
  reviewDialog.value = false
  load()
}

function timeOf(value?: string) {
  if (!value) return '—'
  return value.replace('T', ' ').slice(0, 16)
}
</script>

<template>
  <div v-loading="loading">
    <div class="page-head">
      <h2>沉淀中心</h2>
      <p>高频问答沉淀为 FAQ，未答问题沉淀为知识缺口，形成闭环</p>
      <div style="flex: 1"></div>
      <el-button size="small" @click="load">刷新</el-button>
    </div>

    <div class="metric-grid" style="grid-template-columns: repeat(3, minmax(0, 1fr))">
      <div class="card metric">
        <div class="label"><span>待审核 FAQ</span><span>PENDING</span></div>
        <div class="value">{{ pending.length }}</div>
        <div class="delta">频次 ≥ 5 的相似问题自动沉淀</div>
      </div>
      <div class="card metric">
        <div class="label"><span>已发布 FAQ</span><span>LIVE</span></div>
        <div class="value">{{ published.length }}</div>
        <div class="delta">发布后写入 Redis / 内存缓存，命中不调用模型</div>
      </div>
      <div class="card metric">
        <div class="label"><span>知识缺口</span><span>GAP</span></div>
        <div class="value">{{ gaps.length }}</div>
        <div class="delta">累计提问 {{ gapTotal }} 次未得到有效回答</div>
      </div>
    </div>

    <div class="card card-pad">
      <el-tabs v-model="tab">
        <el-tab-pane :label="`待审核 FAQ（${pending.length}）`" name="pending">
          <div v-if="!pending.length" class="empty-hint">
            暂无待审核 FAQ。当同一类问题累计达到 5 次，系统会自动沉淀为待审核条目。
          </div>
          <div v-for="faq in pending" :key="faq.id" class="source-card">
            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px">
              <div class="q" style="flex: 1">{{ faq.question }}</div>
              <span class="pill blue">命中 {{ faq.hit_count }}</span>
              <span class="pill">{{ faq.category }}</span>
              <span class="pill">{{ faq.source_type === 'auto_mined' ? '自动沉淀' : '手动' }}</span>
            </div>
            <div class="a">{{ faq.answer }}</div>
            <div style="display: flex; gap: 8px; margin-top: 10px">
              <el-button size="small" type="primary" @click="openReview(faq)">审核发布</el-button>
              <el-button size="small" @click="current = faq; editedAnswer = faq.answer; review('reject')">驳回</el-button>
              <div style="flex: 1"></div>
              <span style="font-size: 11.5px; color: #98a2b3">来源：{{ faq.related_unit_title || '—' }}</span>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane :label="`已发布（${published.length}）`" name="published">
          <div v-if="!published.length" class="empty-hint">还没有已发布的 FAQ</div>
          <el-table :data="published" v-else>
            <el-table-column prop="question" label="问题" min-width="220" />
            <el-table-column prop="answer" label="标准答案" min-width="320">
              <template #default="{ row }">
                <div style="max-height: 54px; overflow: hidden; font-size: 12.5px; color: #475467">{{ row.answer }}</div>
              </template>
            </el-table-column>
            <el-table-column prop="hit_count" label="命中" width="80" />
            <el-table-column prop="category" label="分类" width="110" />
            <el-table-column label="缓存" width="90">
              <template #default="{ row }">
                <span class="pill" :class="row.cache_active ? 'green' : ''">
                  {{ row.cache_active ? '已生效' : '未命中' }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="审核时间" width="150">
              <template #default="{ row }">{{ timeOf(row.reviewed_at) }}</template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane :label="`知识缺口（${gaps.length}）`" name="gaps">
          <div v-if="!gaps.length" class="empty-hint">暂无知识缺口，说明当前知识覆盖良好</div>
          <div v-for="gap in gaps" :key="gap.id" class="source-card">
            <div style="display: flex; align-items: center; gap: 8px">
              <div class="q" style="flex: 1">{{ gap.question_pattern }}</div>
              <span class="pill red">提问 {{ gap.ask_count }} 次</span>
              <span class="pill">{{ gap.status === 'unresolved' ? '未解决' : gap.status }}</span>
            </div>
            <div style="font-size: 12px; color: #6b7280; margin-bottom: 6px">
              最近提问：{{ timeOf(gap.last_asked_at) }}
            </div>
            <div style="display: flex; gap: 6px; flex-wrap: wrap">
              <span v-for="(q, i) in gap.sample_questions" :key="i" class="pill">{{ q }}</span>
            </div>
            <div style="margin-top: 10px">
              <el-button size="small" type="primary" plain @click="openGapUnit(gap)">
                一键创建知识单元
              </el-button>
              <el-button size="small" text @click="$router.push({ name: 'workbench' })">去管理助手处理</el-button>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>

    <el-dialog v-model="gapDialog" title="用知识单元补全缺口" width="680px">
      <el-form label-position="top">
        <el-form-item label="知识标题"><el-input v-model="gapForm.title" /></el-form-item>
        <el-form-item label="分类">
          <el-select v-model="gapForm.category" filterable allow-create style="width: 100%">
            <el-option v-for="c in ['财务制度', '人力资源', '产品文档', '行政制度', '技术规范', '未分类']" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="正文（保存后自动切片、向量化并立即可检索）">
          <el-input v-model="gapForm.content" type="textarea" :rows="7" />
        </el-form-item>
        <el-form-item label="数据权限">
          <div style="width: 100%">
            <div style="font-size: 12.5px; color: #6b7280; margin-bottom: 6px">
              {{
                gapTargets.length
                  ? gapTargets.map((t) => t.target_name).filter(Boolean).join('、')
                  : '未配置（保存后仅管理员可见）'
              }}
            </div>
            <el-collapse>
              <el-collapse-item title="展开选择授权对象（全局 / 部门 / 角色 / 人员）" name="perm">
                <PermissionSelector
                  v-model="gapTargets"
                  :departments="departments"
                  :roles="roles"
                  :users="users"
                />
              </el-collapse-item>
            </el-collapse>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="gapDialog = false">取消</el-button>
        <el-button type="primary" :loading="savingGap" @click="saveGapUnit">创建并解决缺口</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="reviewDialog" title="审核 FAQ" width="620px">
      <div v-if="current">
        <div style="font-size: 12.5px; color: #6b7280; margin-bottom: 6px">问题</div>
        <div style="font-weight: 600; margin-bottom: 14px">{{ current.question }}</div>
        <div style="font-size: 12.5px; color: #6b7280; margin-bottom: 6px">标准答案（可编辑）</div>
        <el-input v-model="editedAnswer" type="textarea" :rows="8" />
        <div style="font-size: 12px; color: #98a2b3; margin-top: 10px; line-height: 1.7">
          发布后该问题将直接命中缓存并复用来源单元的权限：
          没有来源单元访问权限的用户不会命中此缓存。
        </div>
      </div>
      <template #footer>
        <el-button @click="reviewDialog = false">取消</el-button>
        <el-button @click="review('reject')">驳回</el-button>
        <el-button type="primary" @click="review('approve')">通过并发布</el-button>
      </template>
    </el-dialog>
  </div>
</template>
