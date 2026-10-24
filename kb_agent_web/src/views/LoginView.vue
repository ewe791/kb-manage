<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()

const form = ref({ username: 'admin', password: 'Admin@123' })
const loading = ref(false)

const demos = [
  { label: '管理员 admin', username: 'admin', password: 'Admin@123', desc: '全部权限' },
  { label: '张三 · 财务专员', username: 'zhangsan', password: 'Zs@123456', desc: '可见财务制度' },
  { label: '李四 · 市场部', username: 'lisi', password: 'Ls@123456', desc: '无财务权限' },
]

function fill(item: { username: string; password: string }) {
  form.value.username = item.username
  form.value.password = item.password
}

async function submit() {
  if (!form.value.username || !form.value.password) {
    ElMessage.warning('请输入账号与密码')
    return
  }
  loading.value = true
  try {
    await auth.login(form.value.username, form.value.password)
    ElMessage.success(`欢迎回来，${auth.user?.display_name || auth.user?.username}`)
    router.push({ name: 'workbench' })
  } catch {
    /* 拦截器已提示 */
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <section class="login-visual">
      <div class="glow"></div>
      <div style="position: relative; z-index: 1">
        <div class="brand" style="padding: 0 0 40px">
          <div class="brand-mark">K</div>
          <div class="brand-text">
            <b style="color: #fff">知识库 Agent</b>
            <span>KNOWLEDGE WORKBENCH</span>
          </div>
        </div>
        <h2>让每一次提问，<br />都落在<em>你被授权</em>的知识里。</h2>
        <p>
          四维权限引擎在检索与生成之间硬性拦截：没有权限的内容不会进入模型上下文，
          也不会以摘要、暗示的形式泄露。模型只负责回答，权限只由代码裁决。
        </p>
      </div>

      <div class="login-features">
        <div class="login-feature">
          <span style="color: #8f9bff">◈</span>
          <div>
            <b>鉴权检索</b>
            <span>先召回、再鉴权、后生成，未授权单元零透出</span>
          </div>
        </div>
        <div class="login-feature">
          <span style="color: #5eead4">◎</span>
          <div>
            <b>四维数据权限</b>
            <span>全局 / 部门 / 角色 / 人员，任一命中即授权</span>
          </div>
        </div>
        <div class="login-feature">
          <span style="color: #ffd479">✧</span>
          <div>
            <b>知识沉淀闭环</b>
            <span>高频问答沉淀 FAQ、识别缺口，反向补齐知识</span>
          </div>
        </div>
      </div>
    </section>

    <section class="login-panel">
      <div class="login-box">
        <h3>登录工作台</h3>
        <p class="hint">使用管理员分配的企业账号登录</p>

        <el-form label-position="top" @submit.prevent>
          <el-form-item label="账号">
            <el-input v-model="form.username" size="large" placeholder="请输入用户名" @keyup.enter="submit" />
          </el-form-item>
          <el-form-item label="密码">
            <el-input
              v-model="form.password"
              size="large"
              type="password"
              show-password
              placeholder="请输入密码"
              @keyup.enter="submit"
            />
          </el-form-item>
          <el-button type="primary" size="large" style="width: 100%; margin-top: 6px" :loading="loading" @click="submit">
            登录
          </el-button>
        </el-form>

        <div class="demo-accounts">
          <div class="t">演示账号（点击填充）</div>
          <div class="demo-row">
            <div v-for="item in demos" :key="item.username" class="demo-chip" @click="fill(item)">
              {{ item.label }}
            </div>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>
