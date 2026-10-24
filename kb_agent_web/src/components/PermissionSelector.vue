<script setup lang="ts">
import { computed, ref, watch } from 'vue'

interface Target {
  target_type: 'global' | 'department' | 'role' | 'user'
  target_id: string | null
  target_name?: string
}

const props = defineProps<{
  modelValue: Target[]
  departments: Array<{ id: string; name: string }>
  roles: Array<{ id: string; role_name: string }>
  users: Array<{ id: string; display_name: string; username: string; department_name?: string }>
}>()

const emit = defineEmits<{ (e: 'update:modelValue', value: Target[]): void }>()

const isGlobal = ref(false)
const deptIds = ref<string[]>([])
const roleIds = ref<string[]>([])
const userIds = ref<string[]>([])

function hydrate(targets: Target[]) {
  isGlobal.value = targets.some((t) => t.target_type === 'global')
  deptIds.value = targets.filter((t) => t.target_type === 'department').map((t) => t.target_id as string)
  roleIds.value = targets.filter((t) => t.target_type === 'role').map((t) => t.target_id as string)
  userIds.value = targets.filter((t) => t.target_type === 'user').map((t) => t.target_id as string)
}

hydrate(props.modelValue || [])

watch(
  () => props.modelValue,
  (value) => hydrate(value || []),
  { deep: true },
)

function sync() {
  const targets: Target[] = []
  if (isGlobal.value) {
    targets.push({ target_type: 'global', target_id: null, target_name: '全体成员' })
  }
  deptIds.value.forEach((id) =>
    targets.push({
      target_type: 'department',
      target_id: id,
      target_name: props.departments.find((d) => d.id === id)?.name,
    }),
  )
  roleIds.value.forEach((id) =>
    targets.push({
      target_type: 'role',
      target_id: id,
      target_name: props.roles.find((r) => r.id === id)?.role_name,
    }),
  )
  userIds.value.forEach((id) => {
    const user = props.users.find((u) => u.id === id)
    targets.push({
      target_type: 'user',
      target_id: id,
      target_name: user?.display_name || user?.username,
    })
  })
  emit('update:modelValue', targets)
}

function toggleGlobal(value: boolean) {
  if (value) {
    deptIds.value = []
    roleIds.value = []
    userIds.value = []
  }
  sync()
}

const summary = computed(() => {
  const parts: string[] = []
  if (isGlobal.value) parts.push('全体成员')
  parts.push(...deptIds.value.map((id) => props.departments.find((d) => d.id === id)?.name || ''))
  parts.push(...roleIds.value.map((id) => props.roles.find((r) => r.id === id)?.role_name || ''))
  parts.push(
    ...userIds.value.map((id) => {
      const u = props.users.find((x) => x.id === id)
      return u?.display_name || u?.username || ''
    }),
  )
  return parts.filter(Boolean)
})
</script>

<template>
  <div class="perm-selector">
    <div class="hint-line">
      四类授权为 OR 关系：任一命中即可访问；未勾选任何对象时默认<strong>不可见</strong>。
    </div>

    <div class="row global-row">
      <el-checkbox :model-value="isGlobal" @update:model-value="toggleGlobal">全局（全体在职员工）</el-checkbox>
    </div>

    <div class="block">
      <div class="label">按部门</div>
      <el-select
        v-model="deptIds"
        multiple
        filterable
        collapse-tags
        collapse-tags-tooltip
        placeholder="选择部门（可多选）"
        :disabled="isGlobal"
        style="width: 100%"
        @change="sync"
      >
        <el-option v-for="d in departments" :key="d.id" :label="d.name" :value="d.id" />
      </el-select>
    </div>

    <div class="block">
      <div class="label">按角色</div>
      <el-select
        v-model="roleIds"
        multiple
        filterable
        collapse-tags
        collapse-tags-tooltip
        placeholder="选择角色（可多选）"
        :disabled="isGlobal"
        style="width: 100%"
        @change="sync"
      >
        <el-option v-for="r in roles" :key="r.id" :label="r.role_name" :value="r.id" />
      </el-select>
    </div>

    <div class="block">
      <div class="label">按人员</div>
      <el-select
        v-model="userIds"
        multiple
        filterable
        collapse-tags
        collapse-tags-tooltip
        placeholder="选择人员（可多选）"
        :disabled="isGlobal"
        style="width: 100%"
        @change="sync"
      >
        <el-option
          v-for="u in users"
          :key="u.id"
          :label="`${u.display_name || u.username}（${u.department_name || '无部门'}）`"
          :value="u.id"
        />
      </el-select>
    </div>

    <div class="summary">
      <span class="label">授权预览</span>
      <div class="perm-tags">
        <span v-if="!summary.length" class="pill red">未授权（仅管理员可见）</span>
        <span v-for="(name, idx) in summary" :key="idx" class="perm-tag">{{ name }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.perm-selector {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.hint-line {
  font-size: 12px;
  color: #6b7280;
  background: #f8f9fc;
  border: 1px solid #e6e8ef;
  border-radius: 10px;
  padding: 9px 12px;
  line-height: 1.6;
}
.row {
  display: flex;
  align-items: center;
}
.block {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.label {
  font-size: 12.5px;
  color: #475467;
  font-weight: 600;
}
.summary {
  border-top: 1px dashed #e6e8ef;
  padding-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
</style>
