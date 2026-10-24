<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '@/api'
import { useAuthStore } from '@/stores/auth'
import PermissionSelector from '@/components/PermissionSelector.vue'

const auth = useAuthStore()
const loading = ref(false)
const units = ref<any[]>([])
const total = ref(0)
const query = reactive({ keyword: '', category: '', file_type: '', status: '', page: 1, page_size: 10 })

const departments = ref<any[]>([])
const roles = ref<any[]>([])
const users = ref<any[]>([])

const editDialog = ref(false)
const editForm = reactive({ id: '', title: '', summary: '', category: '', status: 'active', content: '' })
const originalContent = ref('')
const saving = ref(false)

const detailDrawer = ref(false)
const detail = ref<any>(null)

const permDialog = ref(false)
const permUnit = ref<any>(null)
const targets = ref<any[]>([])
const savingPerm = ref(false)

async function load() {
  loading.value = true
  try {
    const data: any = await api.units({ ...query })
    units.value = data.items
    total.value = data.total
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

onMounted(async () => {
  if (auth.hasPermission('knowledge:permission')) {
    await Promise.all([load(), loadRefs()])
  } else {
    await load()
  }
})

async function openDetail(row: any) {
  detail.value = await api.unit(row.id)
  detailDrawer.value = true
}

async function openEdit(row: any) {
  const data: any = await api.unit(row.id)
  editForm.id = data.id
  editForm.title = data.title
  editForm.summary = data.summary
  editForm.category = data.category
  editForm.status = data.status
  editForm.content = data.content
  originalContent.value = data.content
  editDialog.value = true
}

async function saveEdit() {
  saving.value = true
  try {
    await api.updateUnit(editForm.id, {
      title: editForm.title,
      summary: editForm.summary,
      category: editForm.category,
      status: editForm.status,
      ...(editForm.content !== originalContent.value ? { content: editForm.content } : {}),
    })
    ElMessage.success('已保存，切片与向量索引已同步')
    editDialog.value = false
    load()
  } finally {
    saving.value = false
  }
}

async function openPermissions(row: any) {
  permUnit.value = row
  const data: any = await api.unit(row.id)
  targets.value = (data.permissions || []).map((p: any) => ({
    target_type: p.target_type,
    target_id: p.target_id,
    target_name: p.target_name,
  }))
  permDialog.value = true
}

async function savePermissions() {
  if (!targets.value.length) {
    ElMessage.warning('请至少选择一个授权对象')
    return
  }
  savingPerm.value = true
  try {
    await api.setUnitPermissions(
      permUnit.value.id,
      targets.value.map((t: any) => ({ target_type: t.target_type, target_id: t.target_id })),
    )
    ElMessage.success('权限已更新（全量覆盖）')
    permDialog.value = false
    load()
  } finally {
    savingPerm.value = false
  }
}

async function remove(row: any) {
  await ElMessageBox.confirm(`确定删除《${row.title}》吗？切片、权限与向量索引将同时清理。`, '删除知识单元', {
    type: 'warning',
  })
  await api.deleteUnits([row.id])
  ElMessage.success('已删除')
  load()
}

function permLabel(p: any) {
  const map: any = { global: '全局', department: '部门', role: '角色', user: '人员' }
  return `${map[p.target_type] || p.target_type}：${p.target_name}`
}

function formatTime(value?: string) {
  return value ? value.replace('T', ' ').slice(0, 16) : '—'
}

function formatSize(bytes?: number) {
  if (!bytes) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
</script>

<template>
  <div>
    <div class="page-head">
      <h2>知识单元</h2>
      <p>共 {{ total }} 个单元；权限为全量覆盖式配置，保存后即时生效</p>
      <div style="flex: 1"></div>
      <el-button v-if="auth.hasPermission('knowledge:import')" type="primary" size="small" @click="$router.push({ name: 'import' })">
        导入知识
      </el-button>
    </div>

    <div class="card card-pad">
      <div class="table-toolbar">
        <el-input
          v-model="query.keyword"
          placeholder="搜索标题或正文"
          clearable
          style="width: 230px"
          @keyup.enter="(query.page = 1), load()"
        />
        <el-input v-model="query.category" placeholder="分类" clearable style="width: 130px" @keyup.enter="(query.page = 1), load()" />
        <el-select v-model="query.file_type" placeholder="格式" clearable style="width: 120px" @change="(query.page = 1), load()">
          <el-option label="PDF" value="pdf" />
          <el-option label="Markdown" value="md" />
          <el-option label="Word" value="docx" />
          <el-option label="TXT" value="txt" />
        </el-select>
        <el-select v-model="query.status" placeholder="状态" clearable style="width: 120px" @change="(query.page = 1), load()">
          <el-option label="启用" value="active" />
          <el-option label="归档" value="archived" />
        </el-select>
        <el-button @click="(query.page = 1), load()">查询</el-button>
        <el-button
          text
          @click="query.keyword = ''; query.category = ''; query.file_type = ''; query.status = ''; query.page = 1; load()"
        >
          重置
        </el-button>
      </div>

      <el-table :data="units" v-loading="loading" style="width: 100%">
        <el-table-column label="编号 / 标题" min-width="230">
          <template #default="{ row }">
            <div style="font-weight: 600; cursor: pointer" @click="openDetail(row)">{{ row.title }}</div>
            <div class="mono" style="color: #98a2b3; margin-top: 2px">
              {{ row.unit_code }} · {{ row.source_file_name || '手动创建' }}
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="category" label="分类" width="105" />
        <el-table-column label="格式" width="90">
          <template #default="{ row }">
            <span class="pill">{{ (row.file_type || 'md').toUpperCase() }}</span>
          </template>
        </el-table-column>
        <el-table-column label="权限范围" min-width="220">
          <template #default="{ row }">
            <div class="perm-tags">
              <span v-if="!row.permissions.length" class="pill red">未授权</span>
              <span v-for="(p, i) in row.permissions" :key="i" class="perm-tag" :class="p.target_type">
                {{ permLabel(p) }}
              </span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="创建人" width="100">
          <template #default="{ row }">{{ row.creator_name || '系统' }}</template>
        </el-table-column>
        <el-table-column label="更新时间" width="140">
          <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="85">
          <template #default="{ row }">
            <span class="pill" :class="row.status === 'active' ? 'green' : ''">
              {{ row.status === 'active' ? '启用' : '归档' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button text size="small" @click="openDetail(row)">详情</el-button>
            <el-button text size="small" @click="openEdit(row)" v-if="auth.hasPermission('knowledge:update')">编辑</el-button>
            <el-button
              text
              size="small"
              type="primary"
              @click="openPermissions(row)"
              v-if="auth.hasPermission('knowledge:permission')"
            >
              配权限
            </el-button>
            <el-button text size="small" type="danger" @click="remove(row)" v-if="auth.hasPermission('knowledge:delete')">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div style="display: flex; justify-content: flex-end; margin-top: 14px">
        <el-pagination
          v-model:current-page="query.page"
          v-model:page-size="query.page_size"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="load"
        />
      </div>
    </div>

    <el-drawer v-model="detailDrawer" title="知识单元详情" size="560px">
      <div v-if="detail">
        <div style="font-size: 19px; font-weight: 680; margin-bottom: 6px">{{ detail.title }}</div>
        <div class="mono" style="color: #98a2b3; margin-bottom: 14px">{{ detail.unit_code }}</div>

        <div style="display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px">
          <span class="pill">{{ detail.category }}</span>
          <span class="pill">{{ (detail.file_type || 'md').toUpperCase() }}</span>
          <span class="pill">{{ detail.chunk_count }} 个切片</span>
          <span class="pill">{{ formatSize(detail.file_size) }}</span>
          <span class="pill" :class="detail.status === 'active' ? 'green' : ''">
            {{ detail.status === 'active' ? '启用' : '归档' }}
          </span>
        </div>

        <div class="section-title">数据权限</div>
        <div class="perm-tags" style="margin: 8px 0 16px">
          <span v-if="!detail.permissions.length" class="pill red">未授权（仅管理员可见）</span>
          <span v-for="(p, i) in detail.permissions" :key="i" class="perm-tag" :class="p.target_type">
            {{ permLabel(p) }}
          </span>
        </div>

        <div class="section-title">摘要</div>
        <p style="font-size: 13px; color: #475467; line-height: 1.8">{{ detail.summary || '—' }}</p>

        <div class="section-title" style="margin-top: 14px">正文</div>
        <div
          style="
            margin-top: 8px;
            font-size: 12.5px;
            line-height: 1.9;
            color: #344054;
            white-space: pre-wrap;
            max-height: 340px;
            overflow: auto;
            background: #f9fafc;
            border: 1px solid #e6e8ef;
            border-radius: 10px;
            padding: 12px 14px;
          "
        >
          {{ detail.content }}
        </div>

        <div style="margin-top: 14px; font-size: 12px; color: #98a2b3">
          创建人：{{ detail.creator_name }} · 创建于 {{ formatTime(detail.created_at) }} ·
          更新于 {{ formatTime(detail.updated_at) }}
        </div>

        <div style="margin-top: 18px; display: flex; gap: 8px">
          <el-button
            size="small"
            type="primary"
            v-if="auth.hasPermission('knowledge:permission')"
            @click="detailDrawer = false; openPermissions(detail)"
          >
            配置权限
          </el-button>
          <el-button size="small" v-if="auth.hasPermission('knowledge:update')" @click="detailDrawer = false; openEdit(detail)">
            编辑内容
          </el-button>
        </div>
      </div>
    </el-drawer>

    <el-dialog v-model="editDialog" title="编辑知识单元" width="640px">
      <el-form label-position="top">
        <el-form-item label="标题"><el-input v-model="editForm.title" /></el-form-item>
        <el-form-item label="分类"><el-input v-model="editForm.category" /></el-form-item>
        <el-form-item label="摘要"><el-input v-model="editForm.summary" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="正文（保存后自动重建切片与向量）">
          <el-input v-model="editForm.content" type="textarea" :rows="10" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="editForm.status" style="width: 100%">
            <el-option label="启用" value="active" />
            <el-option label="归档" value="archived" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="permDialog" title="配置数据权限" width="620px">
      <div v-if="permUnit" style="margin-bottom: 14px">
        <div style="font-weight: 600">{{ permUnit.title }}</div>
        <div style="font-size: 12px; color: #98a2b3">保存后为全量覆盖：原有授权将被替换</div>
      </div>
      <PermissionSelector v-model="targets" :departments="departments" :roles="roles" :users="users" />
      <template #footer>
        <el-button @click="permDialog = false">取消</el-button>
        <el-button type="primary" :loading="savingPerm" @click="savePermissions">保存权限</el-button>
      </template>
    </el-dialog>
  </div>
</template>
