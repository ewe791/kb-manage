import { createRouter, createWebHashHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import MainLayout from '@/layouts/MainLayout.vue'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue') },
    {
      path: '/',
      component: MainLayout,
      redirect: '/workbench',
      children: [
        {
          path: 'workbench',
          name: 'workbench',
          component: () => import('@/views/ChatWorkbench.vue'),
          meta: { title: '智能问答', subtitle: '知识库 Agent 工作台', permission: 'ai:access' },
        },
        {
          path: 'knowledge',
          name: 'knowledge',
          component: () => import('@/views/KnowledgePage.vue'),
          meta: { title: '知识管理', subtitle: '知识单元与四维权限', permission: 'knowledge:read' },
        },
        {
          path: 'import',
          name: 'import',
          component: () => import('@/views/ImportPage.vue'),
          meta: { title: '知识导入', subtitle: '批量解析与向量化', permission: 'knowledge:import' },
        },
        {
          path: 'org',
          name: 'org',
          component: () => import('@/views/OrgPage.vue'),
          meta: { title: '组织与权限', subtitle: '用户 / 角色 / 部门', permission: 'org:manage' },
        },
        {
          path: 'dashboard',
          name: 'dashboard',
          component: () => import('@/views/DashboardPage.vue'),
          meta: { title: '运营看板', subtitle: '访问、Token 与知识缺口', permission: 'dashboard:read' },
        },
        {
          path: 'settlement',
          name: 'settlement',
          component: () => import('@/views/SettlementPage.vue'),
          meta: { title: '沉淀中心', subtitle: 'FAQ 审核与知识缺口', permission: 'settlement:review' },
        },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/workbench' },
  ],
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.name === 'login') {
    if (auth.isLoggedIn) return { name: 'workbench' }
    return true
  }
  if (!auth.isLoggedIn) return { name: 'login', query: { redirect: to.fullPath } }
  const permission = to.meta.permission as string | undefined
  if (permission && !auth.hasPermission(permission)) {
    return { name: 'workbench' }
  }
  return true
})

export default router
