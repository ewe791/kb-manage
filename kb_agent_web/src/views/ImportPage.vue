<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { http } from '@/api'

const fileList = ref<any[]>([])
const category = ref('未分类')
const uploading = ref(false)
const progress = ref(0)
const results = ref<any[]>([])
const categories = ['财务制度', '人力资源', '产品文档', '行政制度', '技术规范', '未分类']

function onChange(_file: any, files: any[]) {
  fileList.value = files
}

async function submit() {
  if (!fileList.value.length) {
    ElMessage.warning('请先选择文件')
    return
  }
  uploading.value = true
  progress.value = 0
  const form = new FormData()
  fileList.value.forEach((file: any) => {
    const raw = file.raw || file
    if (raw) form.append('files', raw)
  })
  form.append('category', category.value || '未分类')
  try {
    const data: any = await http.post('/knowledge/import', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (event: any) => {
        if (event.total) progress.value = Math.round((event.loaded / event.total) * 100)
      },
      timeout: 300000,
    })
    results.value = data.items || []
    const ok = data.success_count || 0
    ElMessage.success(`导入完成：成功 ${ok} / 共 ${data.total}`)
    fileList.value = []
  } catch {
    /* 拦截器已提示 */
  } finally {
    uploading.value = false
  }
}
</script>

<template>
  <div>
    <div class="page-head">
      <h2>知识导入</h2>
      <p>支持 PDF / Markdown / Word(.docx) / TXT，自动解析、按 500 字符切片并向量化入库</p>
    </div>

    <div class="split-2">
      <div class="card card-pad">
        <p class="section-title">上传文档</p>
        <p class="section-sub" style="margin-bottom: 14px">单个文件建议不超过 50MB，可一次选择多个</p>

        <el-upload
          drag
          multiple
          :auto-upload="false"
          :file-list="fileList"
          :on-change="onChange"
          :on-remove="onChange"
          accept=".pdf,.md,.markdown,.docx,.txt"
        >
          <div style="font-size: 30px; color: #9aa4ff; margin-bottom: 8px">⇪</div>
          <div style="font-size: 14px; color: #344054">把文件拖到这里，或点击选择</div>
          <div style="font-size: 12px; color: #98a2b3; margin-top: 6px">
            PDF · Markdown · Word · TXT
          </div>
        </el-upload>

        <div style="margin-top: 16px; display: flex; gap: 10px; align-items: center">
          <span style="font-size: 12.5px; color: #475467">分类</span>
          <el-select v-model="category" style="width: 180px" filterable allow-create>
            <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
          </el-select>
          <div style="flex: 1"></div>
          <el-button type="primary" :loading="uploading" @click="submit">开始导入</el-button>
        </div>

        <el-progress v-if="uploading" :percentage="progress" :stroke-width="6" style="margin-top: 14px" />
      </div>

      <div class="card card-pad">
        <p class="section-title">本次导入结果</p>
        <p class="section-sub" style="margin-bottom: 12px">每个文件生成 1 个知识单元，切片写入向量索引</p>

        <div v-if="!results.length" class="empty-hint">
          还没有导入记录。<br />导入后这里会显示解析状态与切片数量。
        </div>
        <div v-else>
          <div v-for="(item, idx) in results" :key="idx" class="upload-result">
            <span
              class="pill"
              :class="item.status === 'success' ? 'green' : 'red'"
              style="flex: 0 0 auto"
            >
              {{ item.status === 'success' ? '成功' : item.status }}
            </span>
            <div style="flex: 1; min-width: 0">
              <div style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap">{{ item.file_name }}</div>
              <div class="mono" style="color: #98a2b3; margin-top: 2px">
                {{ item.chunk_count }} 个切片 · {{ item.unit_id ? item.unit_id.slice(0, 8) : '—' }}
              </div>
            </div>
          </div>
          <div style="margin-top: 14px; display: flex; gap: 8px">
            <el-button size="small" @click="$router.push({ name: 'knowledge' })">去配置权限</el-button>
            <el-button size="small" text @click="$router.push({ name: 'workbench' })">去问答验证</el-button>
          </div>
        </div>
      </div>
    </div>

    <div class="card card-pad" style="margin-top: 16px">
      <p class="section-title">切片与向量化规则</p>
      <div class="split-2" style="margin-top: 10px; gap: 24px">
        <div style="font-size: 12.5px; color: #475467; line-height: 1.9">
          <div>① 保存原文件到 uploads/{user_id}/{uuid}_{filename}</div>
          <div>② PDF 用 pypdf、Word 用 python-docx、MD/TXT 直接读取</div>
          <div>③ 每 500 字符切片，重叠 50 字符，优先保留段落边界</div>
        </div>
        <div style="font-size: 12.5px; color: #475467; line-height: 1.9">
          <div>④ 每个原文件生成 1 个 knowledge_units，切片写入 knowledge_chunks</div>
          <div>⑤ bge-small-zh 编码写入 FAISS 内存索引（不可用时回退内置向量）</div>
          <div>⑥ 返回 {file_name, unit_id, chunk_count, status}</div>
        </div>
      </div>
    </div>
  </div>
</template>
