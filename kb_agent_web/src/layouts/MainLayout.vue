<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const profileOpen = ref(false)

const navItems = [
  { name: 'workbench', label: '智能问答', hint: '对话工作台', permission: 'ai:access', icon: '◈' },
  { name: 'knowledge', label: '知识管理', hint: '单元与权限', permission: 'knowledge:read', icon: '▤' },
  { name: 'import', label: '知识导入', hint: '解析与切片', permission: 'knowledge:import', icon: '↑' },
  { name: 'org', label: '组织与权限', hint: 'RBAC 配置', permission: 'org:manage', icon: '◎' },
  { name: 'dashboard', label: '运营看板', hint: '指标与趋势', permission: 'dashboard:read', icon: '◔' },
  { name: 'settlement', label: '沉淀中心', hint: 'FAQ / 缺口', permission: 'settlement:review', icon: '✧' },
]

const PERMISSION_LABELS: Record<string, string> = {
  'knowledge:create': '新建知识',
  'knowledge:read': '查看知识',
  'knowledge:update': '编辑知识',
  'knowledge:delete': '删除知识',
  'knowledge:import': '导入知识',
  'knowledge:permission': '配置数据权限',
  'ai:access': 'AI 问答访问',
  'dashboard:read': '查看看板',
  'settlement:review': 'FAQ 审核 / 缺口',
  'org:manage': '组织与角色管理',
}

const visibleNav = computed(() => navItems.filter((item) => auth.hasPermission(item.permission)))
const currentTitle = computed(() => (route.meta.title as string) || '智能问答')
const currentSubtitle = computed(() => (route.meta.subtitle as string) || '')

const initials = computed(() => {
  const name = auth.user?.display_name || auth.user?.username || 'U'
  return name.slice(0, 1).toUpperCase()
})

const permissionList = computed(() =>
  auth.permissions.map((code) => ({ code, label: PERMISSION_LABELS[code] || code })),
)

function go(name: string) {
  router.push({ name })
}

function logout() {
  auth.logout()
  profileOpen.value = false
  router.push({ name: 'login' })
}
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">K</div>
        <div class="brand-text">
          <b>知识库 Agent</b>
          <span>KNOWLEDGE WORKBENCH</span>
        </div>
      </div>

      <div class="nav-group-label">工作台</div>
      <div
        v-for="item in visibleNav"
        :key="item.name"
        class="nav-item"
        :class="{ active: route.name === item.name }"
        @click="go(item.name)"
      >
        <span style="width: 16px; text-align: center; opacity: 0.85">{{ item.icon }}</span>
        <span>{{ item.label }}</span>
      </div>

      <div class="sidebar-footer">
        <div class="user-chip" style="cursor: pointer" @click="profileOpen = true">
          <div class="avatar">{{ initials }}</div>
          <div class="meta">
            <b>{{ auth.user?.display_name || auth.user?.username }}</b>
            <span>{{ auth.user?.department_name || '未分配部门' }} · {{ auth.roleLabels.join(' / ') || '无角色' }}</span>
          </div>
          <div class="logout-btn" @click.stop="logout">退出</div>
        </div>
      </div>
    </aside>

    <div class="main-area">
      <header class="topbar">
        <div>
          <h1>{{ currentTitle }}</h1>
          <div class="crumb">{{ currentSubtitle }}</div>
        </div>
        <div class="spacer"></div>
        <span class="pill blue">权限 {{ auth.permissions.length }} 项</span>
        <span class="pill green">服务正常</span>
      </header>
      <main class="content">
        <router-view />
      </main>
    </div>

    <el-dialog v-model="profileOpen" title="个人中心" width="520px">
      <div style="display: flex; gap: 14px; align-items: center; margin-bottom: 18px">
        <div
          style="
            width: 52px;
            height: 52px;
            border-radius: 15px;
            background: linear-gradient(140deg, #6b78ff, #3a45c9);
            color: #fff;
            display: grid;
            place-items: center;
            font-size: 20px;
            font-weight: 700;
          "
        >
          {{ initials }}
        </div>
        <div>
          <div style="font-size: 17px; font-weight: 650">{{ auth.user?.display_name }}</div>
          <div style="font-size: 12.5px; color: #6b7280">
            @{{ auth.user?.username }} · {{ auth.user?.department_name || '未分配部门' }}
          </div>
        </div>
      </div>

      <div class="section-title" style="margin-bottom: 8px">角色</div>
      <div style="display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 16px">
        <span v-for="r in auth.user?.roles || []" :key="r.id" class="perm-tag role">{{ r.role_name }}</span>
        <span v-if="!(auth.user?.roles || []).length" class="pill">无角色</span>
      </div>

      <div class="section-title" style="margin-bottom: 8px">操作权限（{{ permissionList.length }}）</div>
      <div style="display: flex; flex-direction: column; gap: 8px">
        <div
          v-for="p in permissionList"
          :key="p.code"
          style="display: flex; align-items: center; gap: 10px; font-size: 13px"
        >
          <span class="pill green" style="flex: 0 0 auto">已授予</span>
          <span style="flex: 1">{{ p.label }}</span>
          <span class="mono" style="color: #98a2b3">{{ p.code }}</span>
        </div>
        <div v-if="!permissionList.length" class="empty-hint" style="padding: 12px 0">暂无权限点</div>
      </div>

      <div style="margin-top: 18px; border-top: 1px dashed #e6e8ef; padding-top: 14px; font-size: 12px; color: #6b7280">
        数据权限由知识单元的四维授权决定（全局 / 部门 / 角色 / 个人），与操作权限相互独立。
      </div>

      <template #footer>
        <el-button @click="profileOpen = false">关闭</el-button>
        <el-button type="danger" plain @click="logout">退出登录</el-button>
      </template>
    </el-dialog>
  </div>
</template>
