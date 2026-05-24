<script setup>
import { ref, computed, onMounted } from 'vue'
import { useAuthStore } from '../stores/auth.js'
import { BUSINESS_UNITS, yearCST, monthCST } from '../constants.js'
import api from '../api/index.js'

const auth = useAuthStore()
const batches = ref([])
const loading = ref(false)
const loadErr = ref('')

// Upload wizard state
const showUpload = ref(false)
const upBu = ref('')
const upYear = ref(yearCST())
const upMonth = ref(monthCST())
const upFile = ref(null)
const upBatchType = ref('department_detail')
const uploading = ref(false)
const uploadErr = ref('')
const uploadResult = ref(null)   // {batch, row_count, fmt, warnings, pl_check}
const previewTab = ref('l1')     // 'l1' | 'l2'
const publishing = ref(false)

const years = Array.from({ length: 5 }, (_, i) => yearCST() - 2 + i)
const months = Array.from({ length: 12 }, (_, i) => i + 1)

const accessibleBus = computed(() => {
  if (auth.isAdmin) return BUSINESS_UNITS
  return (auth.user?.departments || []).filter(d => BUSINESS_UNITS.includes(d))
})

// ── Submission status state (Opt 8) ──────────────────────────────────────────
const statusYear = ref(yearCST())
const statusMonth = ref(monthCST())
const submissionStatus = ref(null)
const statusLoading = ref(false)

async function loadSubmissionStatus() {
  statusLoading.value = true
  try {
    const res = await api.get('/batches/submission-status', {
      params: { year: statusYear.value, month: statusMonth.value },
    })
    submissionStatus.value = res.data
  } catch (e) {
    submissionStatus.value = null
  } finally {
    statusLoading.value = false }
}

// ── L1 summary grouped for the preview tab ───────────────────────────────────
const l1Rows = computed(() => uploadResult.value?.pl_check?.l1_summary || [])
const l2Rows = computed(() => uploadResult.value?.pl_check?.l2_summary || [])
const kpis   = computed(() => uploadResult.value?.pl_check?.kpis || [])

const KPI_KEYS = new Set(['主营业务收入', '主营业务成本', '运营毛利', '经营毛利', '经营净利'])
const KPI_COLORS = {
  '主营业务收入': '#2e7d32',
  '主营业务成本': '#c62828',
  '运营毛利':    '#1565c0',
  '经营毛利':    '#6a1b9a',
  '经营净利':    '#e65100',
}

function fmtAmt(v) {
  if (v === null || v === undefined) return '—'
  const abs = Math.abs(v)
  if (abs >= 100000000) return (v / 100000000).toFixed(2) + ' 亿'
  if (abs >= 10000) return (v / 10000).toFixed(2) + ' 万'
  return v.toFixed(2)
}

// ── Batch list ────────────────────────────────────────────────────────────────
async function loadBatches() {
  loading.value = true
  loadErr.value = ''
  try {
    const res = await api.get('/batches')
    batches.value = res.data
  } catch (e) {
    loadErr.value = e?.error || '加载失败'
  } finally { loading.value = false }
}

function fmtDt(s) {
  return s ? new Date(s).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '-'
}

async function doDelete(batchId) {
  if (!confirm('确认删除此草稿批次？')) return
  try {
    await api.delete(`/batches/${batchId}`)
    batches.value = batches.value.filter(b => b.id !== batchId)
  } catch (e) { alert(e?.error || '删除失败') }
}

// ── Upload wizard ─────────────────────────────────────────────────────────────
function openUpload() {
  upBu.value = accessibleBus.value[0] || ''
  uploadErr.value = ''
  uploadResult.value = null
  upFile.value = null
  upBatchType.value = 'department_detail'
  previewTab.value = 'l1'
  showUpload.value = true
}

function resetUpload() {
  uploadResult.value = null
  uploadErr.value = ''
  upFile.value = null
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
    fd.append('batch_type', upBatchType.value)
    const res = await api.post('/batches/upload', fd)
    uploadResult.value = res.data
    previewTab.value = 'l1'
  } catch (e) {
    uploadErr.value = e?.error || '上传失败'
  } finally { uploading.value = false }
}

async function doPublish(batchId) {
  if (!confirm('确认发布此批次？发布后将替换同事业部同月份的旧数据。')) return
  publishing.value = true
  try {
    await api.put(`/batches/${batchId}/publish`)
    showUpload.value = false
    uploadResult.value = null
    upFile.value = null
    await loadBatches()
    await loadSubmissionStatus()
    alert('发布成功！数据已生效，可在报表页查看。')
  } catch (e) {
    alert(e?.error || '发布失败')
  } finally { publishing.value = false }
}

async function downloadTemplate() {
  try {
    const res = await api.get('/batches/template', { responseType: 'blob' })
    const url = URL.createObjectURL(res)
    const a = document.createElement('a')
    a.href = url
    a.download = '财务数据导入模板.xlsx'
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) { alert(e?.error || '下载失败') }
}

// completeness label for submission status matrix
function completenessLabel(row) {
  if (!row) return '—'
  const dept = row.department_detail
  const pl = row.profit_loss
  if (dept === 'published' && pl === 'published') return '完整'
  if (dept === 'draft' || pl === 'draft') return '草稿中'
  return '未完整'
}

function statusBadgeClass(status) {
  if (status === 'published') return 'badge badge-success'
  if (status === 'draft') return 'badge badge-warn'
  return 'badge badge-muted'
}

function statusLabel(status) {
  if (status === 'published') return '已发布 ✓'
  if (status === 'draft') return '草稿 ●'
  return '未提交 ○'
}

onMounted(() => {
  loadBatches()
  loadSubmissionStatus()
})
</script>

<template>
  <div>
    <div class="topbar">
      <div>
        <h1>数据加工</h1>
        <div style="font-size:13px;color:var(--muted);margin-top:2px">
          上传金蝶部门明细表 / 利润表 · 核对利润指标 · 发布到报表
        </div>
      </div>
      <div style="display:flex;gap:8px">
        <button class="btn btn-ghost btn-sm" @click="downloadTemplate">下载KXT模板</button>
        <button v-if="auth.canUpload" class="btn btn-primary btn-sm" @click="openUpload">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right:4px"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          上传数据
        </button>
      </div>
    </div>

    <!-- ── Opt 8: Monthly Submission Status Panel ──────────────────────────── -->
    <div class="card" style="margin-bottom:16px">
      <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-bottom:14px">
        <div class="section-title" style="margin:0">月度提交状态</div>
        <div style="display:flex;gap:8px;align-items:center">
          <select v-model="statusYear" class="sel-yr" @change="loadSubmissionStatus">
            <option v-for="y in years" :key="y" :value="y">{{ y }} 年</option>
          </select>
          <select v-model="statusMonth" class="sel-mo" @change="loadSubmissionStatus">
            <option v-for="m in months" :key="m" :value="m">{{ m }} 月</option>
          </select>
        </div>
      </div>

      <div v-if="statusLoading" class="empty" style="padding:16px"><div class="icon">⏳</div>加载中…</div>
      <div v-else-if="!submissionStatus || !submissionStatus.rows?.length" class="empty" style="padding:16px">
        <div class="icon">📋</div>暂无提交数据
      </div>
      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>事业部</th>
              <th>部门明细表</th>
              <th>利润表</th>
              <th>完整度</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in submissionStatus.rows" :key="row.bu">
              <td><strong>{{ row.bu }}</strong></td>
              <td>
                <span :class="statusBadgeClass(row.department_detail)">
                  {{ statusLabel(row.department_detail) }}
                </span>
              </td>
              <td>
                <span :class="statusBadgeClass(row.profit_loss)">
                  {{ statusLabel(row.profit_loss) }}
                </span>
              </td>
              <td>
                <span :class="['badge', row.department_detail === 'published' && row.profit_loss === 'published' ? 'badge-success' : 'badge-muted']">
                  {{ completenessLabel(row) }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-if="loading" class="empty"><div class="icon">⏳</div>加载中…</div>
    <div v-else-if="loadErr" class="empty" style="color:var(--danger)"><div class="icon">⚠️</div>{{ loadErr }}</div>

    <!-- Batch list -->
    <div v-else class="card">
      <div class="section-title">导入批次</div>
      <div v-if="!batches.length" class="empty">
        <div class="icon">📂</div>
        <div>暂无导入记录</div>
        <div style="font-size:12px;color:var(--muted);margin-top:6px">上传金蝶导出的部门明细表，或使用KXT模板手动填报</div>
      </div>
      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>事业部</th><th>年月</th><th>类型</th><th>状态</th>
              <th>行数</th><th>上传人</th><th>上传时间</th><th>发布时间</th><th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="b in batches" :key="b.id">
              <td><strong>{{ b.business_unit }}</strong></td>
              <td>{{ b.year }}年{{ b.month }}月</td>
              <td>
                <span class="badge badge-muted" style="font-size:10px">
                  {{ b.batch_type === 'profit_loss' ? '利润表' : '部门明细表' }}
                </span>
              </td>
              <td>
                <span :class="['badge', b.status === 'published' ? 'badge-success' : 'badge-muted']">
                  {{ b.status === 'published' ? '已发布' : '草稿' }}
                </span>
              </td>
              <td style="color:var(--muted)">{{ b.row_count }}</td>
              <td style="font-size:12px">{{ b.uploaded_by || '-' }}</td>
              <td style="font-size:12px;color:var(--muted)">{{ fmtDt(b.uploaded_at) }}</td>
              <td style="font-size:12px;color:var(--muted)">{{ fmtDt(b.published_at) }}</td>
              <td>
                <div style="display:flex;gap:6px">
                  <button v-if="b.status === 'draft' && auth.canPublish" class="btn btn-ghost btn-sm" @click="doPublish(b.id)">发布</button>
                  <button v-if="b.status === 'draft' && auth.canDelete" class="btn btn-danger btn-sm" @click="doDelete(b.id)">删除</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ── Upload modal ────────────────────────────────────────────────────── -->
    <Transition name="fade">
      <div v-if="showUpload" class="modal-mask" @click.self="showUpload = false">
        <div class="upload-modal">

          <!-- ── Step 1: form ── -->
          <template v-if="!uploadResult">
            <div class="modal-header">
              <h2>上传财务数据</h2>
              <button class="modal-close" @click="showUpload = false">×</button>
            </div>

            <div v-if="uploadErr" class="alert alert-err" style="margin-bottom:16px">{{ uploadErr }}</div>

            <!-- Opt 9: updated format hint mentioning JSON -->
            <div class="fmt-hint">
              <div class="fh-item">
                <span class="fh-dot fh-kd"></span>
                <span><strong>金蝶部门明细表</strong> — 直接上传金蝶导出的Excel（含"科目名称""部门""本期借方""本期贷方"列）</span>
              </div>
              <div class="fh-item">
                <span class="fh-dot fh-tp"></span>
                <span><strong>KXT模板</strong> — 下载模板手动填写四列格式（.xlsx）</span>
              </div>
              <div class="fh-item">
                <span class="fh-dot" style="background:#1565c0"></span>
                <span><strong>JSON格式</strong> — 支持系统导出的 .json 数据文件直接导入</span>
              </div>
            </div>

            <!-- Opt 8 batch_type selector -->
            <div class="form-row">
              <label>报表类型 *</label>
              <div style="display:flex;gap:10px;flex-wrap:wrap">
                <label class="type-chip" :class="{ on: upBatchType === 'department_detail' }">
                  <input type="radio" v-model="upBatchType" value="department_detail" style="display:none" />
                  部门明细表（金蝶 / KXT模板）
                </label>
                <label class="type-chip" :class="{ on: upBatchType === 'profit_loss' }">
                  <input type="radio" v-model="upBatchType" value="profit_loss" style="display:none" />
                  利润表
                </label>
              </div>
            </div>

            <div class="form-row">
              <label>事业部 *</label>
              <select v-model="upBu">
                <option value="">请选择</option>
                <option v-for="bu in accessibleBus" :key="bu" :value="bu">{{ bu }}</option>
              </select>
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
              <div class="form-row">
                <label>年份</label>
                <select v-model="upYear">
                  <option v-for="y in years" :key="y" :value="y">{{ y }} 年</option>
                </select>
              </div>
              <div class="form-row">
                <label>月份</label>
                <select v-model="upMonth">
                  <option v-for="m in months" :key="m" :value="m">{{ m }} 月</option>
                </select>
              </div>
            </div>
            <!-- Opt 9: accept .xlsx and .json -->
            <div class="form-row">
              <label>文件（.xlsx 或 .json）</label>
              <input type="file" accept=".xlsx,.json" @change="e => upFile = e.target.files[0]" style="padding:7px 10px" />
            </div>
            <div class="modal-actions">
              <button class="btn btn-ghost" @click="showUpload = false">取消</button>
              <button class="btn btn-primary" :disabled="uploading" @click="doUpload">
                <span v-if="uploading" class="loading-dot" style="display:inline-block"></span>
                {{ uploading ? '解析中…' : '上传并解析' }}
              </button>
            </div>
          </template>

          <!-- ── Step 2: result preview ── -->
          <template v-else>
            <div class="modal-header">
              <div>
                <h2>数据核对</h2>
                <div style="font-size:12px;color:var(--muted);margin-top:2px">
                  {{ uploadResult.batch?.business_unit }} · {{ uploadResult.batch?.year }}年{{ uploadResult.batch?.month }}月 ·
                  共 {{ uploadResult.row_count }} 行
                  <span v-if="uploadResult.fmt === 'kingdee'" class="badge badge-primary" style="margin-left:6px;font-size:10px">金蝶格式</span>
                  <span v-else-if="uploadResult.fmt === 'json'" class="badge badge-primary" style="margin-left:6px;font-size:10px">JSON格式</span>
                  <span v-else class="badge badge-muted" style="margin-left:6px;font-size:10px">KXT模板</span>
                  <span v-if="uploadResult.batch?.batch_type === 'profit_loss'" class="badge badge-info" style="margin-left:6px;font-size:10px">利润表</span>
                </div>
              </div>
              <button class="modal-close" @click="showUpload = false">×</button>
            </div>

            <!-- Warnings -->
            <div v-if="uploadResult.warnings?.length" class="warn-banner">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
              <div>
                <strong>{{ uploadResult.warnings.length }} 行跳过</strong>：
                {{ uploadResult.warnings.slice(0, 2).join('；') }}{{ uploadResult.warnings.length > 2 ? '…' : '' }}
              </div>
            </div>

            <!-- ── Profit loss simplified view (Opt 8 accessibility) ── -->
            <template v-if="uploadResult.batch?.batch_type === 'profit_loss'">
              <div class="pl-simple-confirm">
                <div style="font-size:20px;margin-bottom:8px">✅</div>
                <div style="font-weight:700;font-size:15px;margin-bottom:4px">利润表已上传</div>
                <div style="color:var(--muted);font-size:13px">共 {{ uploadResult.row_count }} 行数据，请确认后发布。</div>
              </div>
            </template>

            <!-- ── Department detail: P&L check + preview ── -->
            <template v-else>
              <!-- ── P&L 利润表核对 ── -->
              <div class="section-title" style="margin-bottom:10px">利润表核对</div>
              <div class="pl-grid">
                <div v-for="kpi in kpis" :key="kpi.name" class="pl-card" :class="{'pl-calc': kpi.is_calculated}">
                  <div class="pl-label">{{ kpi.name }}</div>
                  <div class="pl-amt" :style="`color:${kpi.amount < 0 ? 'var(--danger)' : (KPI_COLORS[kpi.name] || 'var(--text)')}`">
                    {{ fmtAmt(kpi.amount) }}
                  </div>
                  <div class="pl-tag">{{ kpi.is_calculated ? '计算值' : '汇总值' }}</div>
                </div>
              </div>
              <div class="pl-note">
                集团管理费已单独列示（影响经营净利），不计入管理费用核对项
              </div>

              <!-- ── 明细预览 ── -->
              <div class="section-title" style="margin:16px 0 10px">明细预览（存入数据库的3张表）</div>
              <div class="tabs" style="margin-bottom:12px">
                <button :class="['tab', previewTab === 'l1' ? 'active' : '']" @click="previewTab = 'l1'">
                  一级科目汇总
                </button>
                <button :class="['tab', previewTab === 'l2' ? 'active' : '']" @click="previewTab = 'l2'">
                  二级项目部明细
                </button>
              </div>

              <!-- L1 tab -->
              <div v-if="previewTab === 'l1'" class="preview-scroll">
                <table>
                  <thead><tr><th>一级科目</th><th class="amt">金额</th><th>类型</th></tr></thead>
                  <tbody>
                    <tr
                      v-for="row in l1Rows" :key="row.name"
                      :class="{ 'row-kpi': KPI_KEYS.has(row.name), 'row-calc': row.is_calculated }"
                    >
                      <td :style="KPI_KEYS.has(row.name) ? `font-weight:700;color:${KPI_COLORS[row.name] || 'var(--text)'}` : ''">
                        {{ row.name }}
                      </td>
                      <td class="amt" :style="`color:${row.amount < 0 ? 'var(--danger)' : ''}`">
                        {{ fmtAmt(row.amount) }}
                      </td>
                      <td style="font-size:11px;color:var(--muted)">
                        {{ row.is_calculated ? '⚙ 计算' : '原始' }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <!-- L2 tab -->
              <div v-else class="preview-scroll">
                <table>
                  <thead><tr><th>一级科目</th><th>项目部</th><th class="amt">金额</th></tr></thead>
                  <tbody>
                    <tr v-for="(row, i) in l2Rows" :key="i">
                      <td style="font-size:12px;color:var(--muted)">{{ row.l1_name }}</td>
                      <td style="font-weight:600">{{ row.l2_name }}</td>
                      <td class="amt" :style="`color:${row.amount < 0 ? 'var(--danger)' : ''}`">
                        {{ fmtAmt(row.amount) }}
                      </td>
                    </tr>
                    <tr v-if="!l2Rows.length">
                      <td colspan="3" style="text-align:center;color:var(--muted);padding:20px">未检测到项目部维度数据</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </template>

            <div class="modal-actions">
              <button class="btn btn-ghost" @click="resetUpload">重新上传</button>
              <button class="btn btn-ghost" @click="showUpload = false">稍后发布</button>
              <button class="btn btn-primary" :disabled="publishing" @click="doPublish(uploadResult.batch.id)">
                {{ publishing ? '发布中…' : '确认发布' }}
              </button>
            </div>
          </template>

        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.upload-modal {
  background: rgba(255,252,248,0.96);
  backdrop-filter: blur(24px);
  border-radius: 18px;
  width: min(860px, 95vw);
  max-height: 90vh;
  overflow-y: auto;
  padding: 28px 32px;
  box-shadow: 0 24px 72px rgba(100,60,30,0.22);
}
.modal-header { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 20px; }
.modal-header h2 { font-size: 18px; font-weight: 700; }
.modal-close { background: none; border: none; font-size: 22px; color: var(--muted); cursor: pointer; line-height: 1; padding: 0 4px; }

/* Format hint */
.fmt-hint { background: rgba(201,99,66,0.05); border: 1px solid rgba(201,99,66,0.15); border-radius: 10px; padding: 12px 14px; margin-bottom: 18px; display: flex; flex-direction: column; gap: 8px; }
.fh-item { display: flex; align-items: flex-start; gap: 8px; font-size: 13px; }
.fh-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; margin-top: 4px; }
.fh-kd { background: var(--primary); }
.fh-tp { background: var(--muted); }

/* Warning banner */
.warn-banner { display: flex; align-items: flex-start; gap: 8px; padding: 10px 14px; border-radius: 8px; background: rgba(245,127,23,0.08); border: 1px solid rgba(245,127,23,0.2); color: #b45309; font-size: 13px; margin-bottom: 16px; }

/* P&L check grid */
.pl-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin-bottom: 8px; }
@media (max-width: 700px) { .pl-grid { grid-template-columns: repeat(3, 1fr); } }
.pl-card {
  background: rgba(255,252,248,0.8); border: 1.5px solid var(--border);
  border-radius: 12px; padding: 12px 14px; text-align: center;
}
.pl-calc { border-left: 3px solid rgba(201,99,66,.4); }
.pl-label { font-size: 11px; color: var(--muted); font-weight: 600; margin-bottom: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.pl-amt { font-size: 16px; font-weight: 700; margin-bottom: 4px; }
.pl-tag { font-size: 10px; color: rgba(155,128,112,0.5); }
.pl-note { font-size: 11px; color: rgba(155,128,112,0.7); margin-bottom: 4px; padding-left: 4px; }

/* Profit loss simple confirmation */
.pl-simple-confirm {
  text-align: center; padding: 28px 20px;
  background: rgba(46,125,50,0.05); border: 1px solid rgba(46,125,50,0.2);
  border-radius: 12px; margin-bottom: 16px;
}

/* Preview table */
.preview-scroll { max-height: 220px; overflow-y: auto; border-radius: 8px; border: 1px solid var(--border); }
.preview-scroll table { width: 100%; border-collapse: collapse; }
.preview-scroll th, .preview-scroll td { padding: 7px 10px; font-size: 12px; border-bottom: 1px solid var(--border); text-align: left; }
.preview-scroll th { background: rgba(0,0,0,0.03); font-weight: 600; color: var(--muted); position: sticky; top: 0; }
.row-kpi td:first-child { font-weight: 700; }
.row-calc { background: rgba(201,99,66,0.04); }
td.amt, th.amt { text-align: right; font-variant-numeric: tabular-nums; }

.modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px; padding-top: 16px; border-top: 1px solid var(--border); }

.loading-dot {
  width: 12px; height: 12px; border-radius: 50%; margin-right: 6px;
  border: 2px solid rgba(255,255,255,0.4); border-top-color: white;
  animation: spin 0.7s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* Batch type chip selector */
.type-chip {
  display: inline-flex; align-items: center; padding: 6px 14px;
  border-radius: 14px; font-size: 12px; cursor: pointer;
  border: 1.5px solid var(--border); background: rgba(255,253,250,.7); color: var(--muted);
  transition: all .16s; user-select: none;
}
.type-chip:hover { border-color: var(--primary); color: var(--primary); }
.type-chip.on { border-color: var(--primary); background: rgba(201,99,66,.1); color: var(--primary); font-weight: 600; }

/* Status badge variants */
.badge-warn { background: rgba(245,127,23,0.12); color: #b45309; }
.badge-info { background: rgba(21,101,192,0.1); color: #1565c0; }
</style>
