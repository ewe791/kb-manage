<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '@/api'

const tab = ref('users')
const users = ref<any[]>([])
const roles = ref<any[]>([])
const departments = ref<any[]>([])
const tree = ref<any[]>([])
const members = ref<any[]>([])
const codes = ref<string[]>([])
const total = ref(0)
const loading = ref(false)
const userQuery = reactive({ keyword: '', department_id: '', status: '' })

const PERMISSION_META: Record<string, { label: string; group: string }> = {
  'knowledge:create': { label: '新建知识单元', group: '知识' },
  'knowledge:read': { label: '查看知识单元', group: '知识' },
  'knowledge:update': { label: '编辑知识单元', group: '知识' },
  'knowledge:delete': { label: '删除知识单元', group: '知识' },
  'knowledge:import': { label: '导入 / 批量导入', group: '知识' },
  'knowledge:permission': { label: '配置数据权限', group: '知识' },
  'ai:access': { label: 'AI 问答访问', group: 'AI 与运营' },
  'dashboard:read': { label: '查看运营看板', group: 'AI 与运营' },
  'settlement:review': { label: 'FAQ 审核 / 知识缺口', group: 'AI 与运营' },
  'org:manage': { label: '组织与角色管理', group: '组织' },
}
const permissionGroups = ['知识', 'AI 与运营', '组织']

const userDialog = ref(false)
const isEdit = ref(false)
const userForm = reactive({
  id: '',
  username: '',
  password: '',
  display_name: '',
  department_id: '',
  role_ids: [] as string[],
})

const roleDialog = ref(false)
const roleForm = reactive({ id: '', role_name: '', role_code: '', description: '', permissions: [] as string[] })

const deptDialog = ref(false)
const deptForm = reactive({ id: '', name: '', parent_id: '', leader_id: '', sort_order: 0 })

async function load() {
  loading.value = true
  try {
    const [u, r, d, t, c]: any = await Promise.all([
      api.users({ page_size: 100, ...userQuery }),
      api.roles(),
      api.departments(),
      api.departmentTree(),
      api.permissionCodes(),
    ])
    users.value = u.items || []
    total.value = u.total || 0
    roles.value = r || []
    departments.value = d || []
    tree.value = t || []
    codes.value = c || []
  } finally {
    loading.value = false
  }
}

onMounted(load)

function openCreateUser() {
  isEdit.value = false
  Object.assign(userForm, {
    id: '',
    username: '',
    password: '',
    display_name: '',
    department_id: '',
    role_ids: [],
  })
  userDialog.value = true
}

function openEditUser(row: any) {
  isEdit.value = true
  Object.assign(userForm, {
    id: row.id,
    username: row.username,
    password: '',
    display_name: row.display_name,
    department_id: row.department_id || '',
    role_ids: (row.roles || []).map((r: any) => r.id),
  })
  userDialog.value = true
}

async function saveUser() {
  if (isEdit.value) {
    await api.updateUser(userForm.id, {
      display_name: userForm.display_name,
      department_id: userForm.department_id || null,
      role_ids: userForm.role_ids,
      ...(userForm.password ? { password: userForm.password } : {}),
    })
    ElMessage.success('用户已更新')
  } else {
    if (!userForm.username || !userForm.password) {
      ElMessage.warning('用户名与初始密码必填')
      return
    }
    await api.createUser({
      username: userForm.username,
      password: userForm.password,
      display_name: userForm.display_name || userForm.username,
      department_id: userForm.department_id || null,
      role_ids: userForm.role_ids,
    })
    ElMessage.success('用户已创建')
  }
  userDialog.value = false
  load()
}

async function toggleUserStatus(row: any) {
  const next = row.status === 'active' ? 'disabled' : 'active'
  await api.updateUser(row.id, { status: next })
  ElMessage.success(next === 'active' ? '已启用' : '已停用')
  load()
}

async function resetPassword(row: any) {
  await ElMessageBox.confirm(`将 ${row.display_name} 的密码重置为默认初始密码？`, '重置密码', { type: 'warning' })
  const data: any = await api.resetPassword(row.id)
  await ElMessageBox.alert(`账号：${data.username}\n新密码：${data.password}`, '重置成功', { type: 'success' })
}

function openRole(role: any) {
  Object.assign(roleForm, {
    id: role.id,
    role_name: role.role_name,
    role_code: role.role_code,
    description: role.description,
    permissions: [...(role.permissions || [])],
  })
  roleDialog.value = true
}

async function saveRole() {
  await api.assignRolePermissions(roleForm.id, roleForm.permissions)
  await api.updateRole(roleForm.id, { role_name: roleForm.role_name, description: roleForm.description })
  ElMessage.success('角色权限已保存')
  roleDialog.value = false
  load()
}

function openCreateRole() {
  Object.assign(roleForm, { id: '', role_name: '', role_code: '', description: '', permissions: [] })
  roleDialog.value = true
}

async function saveNewRole() {
  if (!roleForm.role_name || !roleForm.role_code) {
    ElMessage.warning('角色名称与编码必填')
    return
  }
  await api.createRole({
    role_name: roleForm.role_name,
    role_code: roleForm.role_code,
    description: roleForm.description,
    permissions: roleForm.permissions,
  })
  ElMessage.success('角色已创建')
  roleDialog.value = false
  load()
}

function openEditDept(dept: any) {
  Object.assign(deptForm, {
    id: dept.id,
    name: dept.name,
    parent_id: dept.parent_id || '',
    leader_id: dept.leader_id || '',
    sort_order: dept.sort_order,
  })
  deptDialog.value = true
}

async function saveDept() {
  if (deptForm.id) {
    await api.updateDepartment(deptForm.id, {
      name: deptForm.name,
      parent_id: deptForm.parent_id || null,
      leader_id: deptForm.leader_id || null,
      sort_order: deptForm.sort_order,
    })
    ElMessage.success('部门已更新')
  } else {
    if (!deptForm.name) {
      ElMessage.warning('部门名称必填')
      return
    }
    await api.createDepartment({
      name: deptForm.name,
      parent_id: deptForm.parent_id || null,
      leader_id: deptForm.leader_id || null,
      sort_order: deptForm.sort_order,
    })
    ElMessage.success('部门已创建')
  }
  deptDialog.value = false
  load()
}

async function showMembers(dept: any) {
  const data: any = await api.departmentMembers(dept.id)
  members.value = data || []
  ElMessage.info(`${dept.name} 共 ${members.value.length} 名成员`)
}

function newDept() {
  Object.assign(deptForm, { id: '', name: '', parent_id: '', leader_id: '', sort_order: 0 })
  deptDialog.value = true
}

function permLabel(code: string) {
  return PERMISSION_META[code]?.label || code
}
</script>

<template>
  <div>
    <div class="page-head">
      <h2>组织与权限</h2>
      <p>操作权限由角色决定，数据权限由知识单元的四维授权决定，二者相互独立</p>
    </div>

    <div class="card card-pad">
      <el-tabs v-model="tab">
        <el-tab-pane label="用户" name="users">
          <div class="table-toolbar">
            <el-input
              v-model="userQuery.keyword"
              placeholder="搜索账号或姓名"
              clearable
              style="width: 200px"
              @keyup.enter="load"
            />
            <el-select v-model="userQuery.department_id" placeholder="部门" clearable style="width: 150px" @change="load">
              <el-option v-for="d in departments" :key="d.id" :label="d.name" :value="d.id" />
            </el-select>
            <el-select v-model="userQuery.status" placeholder="状态" clearable style="width: 120px" @change="load">
              <el-option label="启用" value="active" />
              <el-option label="停用" value="disabled" />
            </el-select>
            <el-button @click="load">查询</el-button>
            <div style="flex: 1"></div>
            <span style="font-size: 12.5px; color: #6b7280">共 {{ total }} 个账号</span>
            <el-button type="primary" size="small" @click="openCreateUser">新建用户</el-button>
          </div>

          <el-table :data="users" v-loading="loading">
            <el-table-column label="用户" min-width="170">
              <template #default="{ row }">
                <div style="font-weight: 600">{{ row.display_name }}</div>
                <div style="font-size: 11.5px; color: #98a2b3">@{{ row.username }}</div>
              </template>
            </el-table-column>
            <el-table-column label="部门" width="130">
              <template #default="{ row }">{{ row.department_name || '—' }}</template>
            </el-table-column>
            <el-table-column label="角色" min-width="170">
              <template #default="{ row }">
                <span v-for="r in row.roles" :key="r.id" class="perm-tag role" style="margin-right: 6px">
                  {{ r.role_name }}
                </span>
                <span v-if="!row.roles?.length" style="color: #98a2b3; font-size: 12px">无角色</span>
              </template>
            </el-table-column>
            <el-table-column label="操作权限" min-width="240">
              <template #default="{ row }">
                <div class="perm-tags">
                  <span v-for="p in (row.permissions || []).slice(0, 3)" :key="p" class="perm-tag">{{ permLabel(p) }}</span>
                  <span v-if="(row.permissions || []).length > 3" class="pill">+{{ row.permissions.length - 3 }}</span>
                  <span v-if="!(row.permissions || []).length" class="pill red">无</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-switch
                  :model-value="row.status === 'active'"
                  size="small"
                  inline-prompt
                  active-text="启用"
                  inactive-text="停用"
                  @change="toggleUserStatus(row)"
                />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="200" fixed="right">
              <template #default="{ row }">
                <el-button text size="small" @click="openEditUser(row)">编辑</el-button>
                <el-button text size="small" @click="resetPassword(row)">重置密码</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="角色" name="roles">
          <div class="table-toolbar">
            <span style="font-size: 12.5px; color: #6b7280">角色的权限点决定菜单可见性与按钮可用性</span>
            <div style="flex: 1"></div>
            <el-button type="primary" size="small" @click="openCreateRole">新建角色</el-button>
          </div>
          <div class="split-2">
            <div v-for="role in roles" :key="role.id" class="source-card">
              <div style="display: flex; align-items: center; gap: 8px">
                <div class="q" style="flex: 1">{{ role.role_name }}</div>
                <span class="pill">{{ role.role_code }}</span>
                <el-button text size="small" type="primary" @click="openRole(role)">配置权限</el-button>
              </div>
              <div style="font-size: 12px; color: #6b7280; margin-bottom: 8px">{{ role.description || '暂无描述' }}</div>
              <div class="perm-tags">
                <span v-for="p in role.permissions" :key="p" class="perm-tag">{{ permLabel(p) }}</span>
                <span v-if="!role.permissions.length" class="pill red">无权限点</span>
              </div>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="部门" name="departments">
          <div class="table-toolbar">
            <span style="font-size: 12.5px; color: #6b7280">部门是四维数据权限的一维，支持树形层级</span>
            <div style="flex: 1"></div>
            <el-button type="primary" size="small" @click="newDept">新建部门</el-button>
          </div>

          <div class="split-2">
            <div class="card card-pad" style="box-shadow: none">
              <el-tree :data="tree" node-key="id" default-expand-all :expand-on-click-node="false">
                <template #default="{ data }">
                  <div style="display: flex; align-items: center; gap: 10px; width: 100%; padding: 4px 0">
                    <span style="font-size: 13px; font-weight: 600">{{ data.name }}</span>
                    <span class="pill">{{ data.member_count }} 人</span>
                    <span v-if="data.leader_name" class="pill blue">负责人 {{ data.leader_name }}</span>
                    <div style="flex: 1"></div>
                    <el-button text size="small" @click.stop="showMembers(data)">成员</el-button>
                    <el-button text size="small" type="primary" @click.stop="openEditDept(data)">编辑</el-button>
                  </div>
                </template>
              </el-tree>
              <div v-if="!tree.length" class="empty-hint">暂无部门</div>
            </div>

            <div class="card card-pad" style="box-shadow: none">
              <p class="section-title">部门成员</p>
              <p class="section-sub" style="margin-bottom: 10px">点击左侧「成员」查看</p>
              <div v-if="!members.length" class="empty-hint" style="padding: 22px 0">暂未选择部门</div>
              <div v-for="m in members" :key="m.id" class="upload-result">
                <span class="pill blue">{{ m.display_name?.slice(0, 1) }}</span>
                <div style="flex: 1">
                  <div style="font-weight: 600">{{ m.display_name }}</div>
                  <div style="font-size: 11.5px; color: #98a2b3">@{{ m.username }} · {{ m.department_name }}</div>
                </div>
                <span v-for="r in m.roles" :key="r.id" class="perm-tag role">{{ r.role_name }}</span>
              </div>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>

    <el-dialog v-model="userDialog" :title="isEdit ? '编辑用户' : '新建用户'" width="520px">
      <el-form label-position="top">
        <el-form-item label="用户名（登录账号）">
          <el-input v-model="userForm.username" :disabled="isEdit" placeholder="例如 zhangsan" />
        </el-form-item>
        <el-form-item :label="isEdit ? '重置密码（留空则不修改）' : '初始密码'">
          <el-input v-model="userForm.password" type="password" show-password placeholder="至少 6 位" />
        </el-form-item>
        <el-form-item label="姓名"><el-input v-model="userForm.display_name" /></el-form-item>
        <el-form-item label="部门">
          <el-select v-model="userForm.department_id" clearable style="width: 100%">
            <el-option v-for="d in departments" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="userForm.role_ids" multiple style="width: 100%">
            <el-option v-for="r in roles" :key="r.id" :label="r.role_name" :value="r.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="userDialog = false">取消</el-button>
        <el-button type="primary" @click="saveUser">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="roleDialog" :title="roleForm.id ? '配置角色权限' : '新建角色'" width="560px">
      <el-form label-position="top">
        <el-form-item label="角色名称"><el-input v-model="roleForm.role_name" /></el-form-item>
        <el-form-item label="角色编码">
          <el-input v-model="roleForm.role_code" :disabled="!!roleForm.id" placeholder="例如 finance_specialist" />
        </el-form-item>
        <el-form-item label="描述"><el-input v-model="roleForm.description" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="操作权限">
          <div style="width: 100%; border: 1px solid #e6e8ef; border-radius: 10px; padding: 12px 14px; max-height: 42vh; overflow: auto">
            <div v-for="group in permissionGroups" :key="group" style="margin-bottom: 10px">
              <div style="font-size: 12px; color: #6b7280; margin-bottom: 6px">{{ group }}</div>
              <el-checkbox-group v-model="roleForm.permissions">
                <el-checkbox
                  v-for="code in codes.filter((c) => PERMISSION_META[c]?.group === group)"
                  :key="code"
                  :value="code"
                  style="width: 46%"
                >
                  {{ permLabel(code) }}
                </el-checkbox>
              </el-checkbox-group>
            </div>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="roleDialog = false">取消</el-button>
        <el-button type="primary" @click="roleForm.id ? saveRole() : saveNewRole()">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="deptDialog" :title="deptForm.id ? '编辑部门' : '新建部门'" width="460px">
      <el-form label-position="top">
        <el-form-item label="部门名称"><el-input v-model="deptForm.name" /></el-form-item>
        <el-form-item label="上级部门">
          <el-select v-model="deptForm.parent_id" clearable style="width: 100%">
            <el-option
              v-for="d in departments.filter((x) => x.id !== deptForm.id)"
              :key="d.id"
              :label="d.name"
              :value="d.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="负责人">
          <el-select v-model="deptForm.leader_id" clearable style="width: 100%">
            <el-option
              v-for="u in users"
              :key="u.id"
              :label="`${u.display_name}（${u.department_name || '无部门'}）`"
              :value="u.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="排序"><el-input-number v-model="deptForm.sort_order" :min="0" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="deptDialog = false">取消</el-button>
        <el-button type="primary" @click="saveDept">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
