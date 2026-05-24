<script setup>
import { ref, onMounted } from 'vue'
import { useAuthStore } from '../stores/auth.js'
import { BUSINESS_UNITS, yearCST, monthCST } from '../constants.js'
import api from '../api/index.js'

const auth = useAuthStore()
const batches = ref([])
const loading = ref(false)
const loadErr = ref('')

// Upload state
const showUpload = ref(false)
const upBu = ref('')
const upYear = ref(yearCST())
const upMonth = ref(monthCST())
const upFile = ref(null)
const uploading = ref(false)
const uploadErr = ref('')
const uploadResult = ref(null)

// Preview confirm state
const pendingBatch = ref(null)
const publishing = ref(false)

const years = Array.from({ length: 5 }, (_, i) => yearCST() - 2 + i)
const months = Array.from({ length: 12 }, (_, i) => i + 1)

async function loadBatches() {
  loading.value = true
  loadErr.value = ''
  try {
    const res = await api.get('/batches')
    batches.value = res.data
  } catch (e) {
    loadErr.value = e?.error || '加载失败'
  } finally {
    loading.value = false
  }
}

function onFileChange(e) {
  upFile.value = e.target.files[0] || null
}

async function doUpload() {
  if (!upBu.value) { uploadErr.value = '请选择事业部'; return }
  if (!upFile.value) { uploadErr.value = '请选择文件'; return }
  uploadErr.value = ''
  uploading.value = true
  uploadResult.value = null
  try {
    const fd = new FormData()
    fd.append('bu', upBu.value)
    fd.append('year', upYear.value)
    fd.append('month', upMonth.value)
    fd.append('file', upFile.value)
    const res = await api.post('/batches/upload', fd)
    uploadResult.value = res.data
    pendingBatch.value = res.data.batch
  } catch (e) {
    uploadErr.value = e?.error || '上传失败'
  } finally {
    uploading.value = false
  }
}

async function doPublish(batchId) {
  if (!confirm('确认发布此批次？发布后将替换同事业部同月份的旧数据。')) return
  publishing.value = true
  try {
    await api.put(`/batches/${batchId}/publish`)
    showUpload.value = false
    uploadResult.value = null
    pendingBatch.value = null
    upFile.value = null
    await loadBatches()
  } catch (e) {
    alert(e?.error || '发布失败')
  } finally {
    publishing.value = false
  }
}

async function doDelete(batchId) {
  if (!confirm('确认删除此草稿批次？')) return
  try {
    await api.delete(`/batches/${batchId}`)
    batches.value = batches.value.filter(b => b.id !== batchId)
  } catch (e) {
    alert(e?.error || '删除失败')
  }
}

async function downloadTemplate() {
  try {
    const res = await api.get('/batches/template', { responseType: 'blob' })
    const url = URL.createObjectURL(res)
    const a = document.createElement('a'); a.href = url; a.download = '财务数据导入模板.xlsx'; a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    alert(e?.error || '下载失败')
  }
}

function fmtDt(s) {
  return s ? new Date(s).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '-'
}

onMounted(loadBatches)
</script>

<template>
  <div>
    <div class="topbar">
      <h1>数据加工</h1>
      <div style="display:flex;gap:8px">
        <button class="btn btn-ghost btn-sm" @click="downloadTemplate">下载模板</button>
        <button v-if="auth.canUpload" class="btn btn-primary btn-sm" @click="showUpload = true">上传数据</button>
      </div>
    </div>

    <div v-if="loading" class="empty"><div class="icon">⏳</div>加载中…</div>
    <div v-else-if="loadErr" class="empty" style="color:var(--danger)"><div class="icon">⚠️</div>{{ loadErr }}</div>

    <div v-else class="card">
      <div class="section-title">导入批次列表</div>
      <div v-if="!batches.length" class="empty"><div class="icon">📭</div>暂无导入记录</div>
      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>事业部</th>
              <th>年月</th>
              <th>状态</th>
              <th>行数</th>
              <th>上传人</th>
              <th>上传时间</th>
              <th>发布时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="b in batches" :key="b.id">
              <td>{{ b.business_unit }}</td>
              <td>{{ b.year }}年{{ b.month }}月</td>
              <td>
                <span :class="['badge', b.status === 'published' ? 'badge-success' : 'badge-muted']">
                  {{ b.status === 'published' ? '已发布' : '草稿' }}
                </span>
              </td>
              <td>{{ b.row_count }}</td>
              <td>{{ b.uploaded_by || '-' }}</td>
              <td>{{ fmtDt(b.uploaded_at) }}</td>
              <td>{{ fmtDt(b.published_at) }}</td>
              <td>
                <div style="display:flex;gap:6px">
                  <button
                    v-if="b.status === 'draft' && auth.canPublish"
                    class="btn btn-ghost btn-sm"
                    @click="doPublish(b.id)"
                  >发布</button>
                  <button
                    v-if="b.status === 'draft' && auth.canDelete"
                    class="btn btn-danger btn-sm"
                    @click="doDelete(b.id)"
                  >删除</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Upload modal -->
    <Transition name="fade">
      <div v-if="showUpload" class="modal-mask" @click.self="showUpload = false">
        <div class="modal-box">
          <h2>上传数据文件</h2>
          <div v-if="uploadErr" class="error-banner">{{ uploadErr }}</div>

          <template v-if="!uploadResult">
            <div class="form-grid form-grid-2">
              <div class="form-row">
                <label>事业部</label>
                <select v-model="upBu">
                  <option value="">请选择</option>
                  <option v-for="bu in BUSINESS_UNITS" :key="bu" :value="bu">{{ bu }}</option>
                </select>
              </div>
              <div class="form-row" style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
                <div>
                  <label>年份</label>
                  <select v-model="upYear">
                    <option v-for="y in years" :key="y" :value="y">{{ y }}</option>
                  </select>
                </div>
                <div>
                  <label>月份</label>
                  <select v-model="upMonth">
                    <option v-for="m in months" :key="m" :value="m">{{ m }}</option>
                  </select>
                </div>
              </div>
            </div>
            <div class="form-row">
              <label>Excel 文件（.xlsx）</label>
              <input type="file" accept=".xlsx" @change="onFileChange" style="padding:7px 10px" />
            </div>
            <div class="modal-actions">
              <button class="btn btn-ghost" @click="showUpload = false">取消</button>
              <button class="btn btn-primary" :disabled="uploading" @click="doUpload">
                {{ uploading ? '上传中…' : '上传并预览' }}
              </button>
            </div>
          </template>

          <template v-else>
            <div class="upload-result">
              <div class="result-stat">
                共解析 <strong>{{ uploadResult.row_count }}</strong> 行有效数据
              </div>
              <div class="section-title" style="margin-top:16px">数据预览（前10行）</div>
              <div class="table-wrap" style="max-height:240px;overflow-y:auto">
                <table>
                  <thead>
                    <tr><th>一级科目</th><th>二级项目部</th><th>三级科目明细</th><th class="amt">金额</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, i) in uploadResult.preview" :key="i">
                      <td>{{ row.l1 }}</td>
                      <td>{{ row.l2 || '-' }}</td>
                      <td>{{ row.l3 || '-' }}</td>
                      <td class="amt">{{ row.amount?.toLocaleString() }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div class="modal-actions">
                <button class="btn btn-ghost" @click="uploadResult = null; uploadErr = ''">重新上传</button>
                <button class="btn btn-primary" :disabled="publishing" @click="doPublish(pendingBatch.id)">
                  {{ publishing ? '发布中…' : '确认发布' }}
                </button>
              </div>
            </div>
          </template>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.upload-result .result-stat { font-size: 14px; color: var(--text); padding: 12px; background: rgba(46,125,50,.07); border-radius: 8px; }
</style>
