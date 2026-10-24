import { defineStore } from 'pinia'
import { api } from '@/api'

interface RoleItem {
  id: string
  role_name: string
  role_code: string
}

interface UserInfo {
  id: string
  username: string
  display_name: string
  department_name?: string | null
  roles: RoleItem[]
  permissions?: string[]
}

const TOKEN_KEY = 'kb_token'
const USER_KEY = 'kb_user'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem(TOKEN_KEY) || '',
    user: JSON.parse(localStorage.getItem(USER_KEY) || 'null') as UserInfo | null,
    permissions: (JSON.parse(localStorage.getItem(USER_KEY) || 'null')?.permissions || []) as string[],
  }),
  getters: {
    isLoggedIn: (state) => !!state.token,
    hasPermission: (state) => (code?: string) => {
      if (!code) return true
      return state.permissions.includes(code)
    },
    roleLabels: (state) => (state.user?.roles || []).map((r) => r.role_name),
    isAdmin: (state) => state.permissions.includes('org:manage') || state.permissions.includes('knowledge:permission'),
  },
  actions: {
    async login(username: string, password: string) {
      const data: any = await api.login(username, password)
      this.token = data.access_token
      this.user = data.user_info
      this.permissions = data.permissions || data.user_info?.permissions || []
      localStorage.setItem(TOKEN_KEY, this.token)
      localStorage.setItem(USER_KEY, JSON.stringify({ ...data.user_info, permissions: this.permissions }))
      return data
    },
    async refresh() {
      const me: any = await api.me()
      this.user = me
      this.permissions = me.permissions || []
      localStorage.setItem(USER_KEY, JSON.stringify(me))
    },
    logout() {
      this.token = ''
      this.user = null
      this.permissions = []
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(USER_KEY)
    },
  },
})
