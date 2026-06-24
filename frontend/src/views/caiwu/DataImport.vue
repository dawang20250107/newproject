<script setup>
import { ref, computed, onMounted } from 'vue'
import { useCaiwuAuth } from '../../composables/useCaiwuAuth.js'
import { BUSINESS_UNITS, yearCST, lastMonthCST } from '../../constants.js'
import api from '../../api/caiwu.js'
import { fmtCompact, fmtDateTime } from '../../utils/format.js'
import EmptyState from '../../components/EmptyState.vue'

const auth = useCaiwuAuth()
const batches = ref([])
const loading = ref(false)
const loadErr = ref('')

// Upload wizard state
const showUpload = ref(false)
const upBu = ref('')
// 默认上月：通常导入的是刚结账的上一个月
const upYear = ref(lastMonthCST().year)
const upMonth = ref(lastMonthCST().month)
const upFile = ref(null)
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
const statusYear = ref(lastMonthCST().year)
const statusMonth = ref(lastMonthCST().month)
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

// 亿/万 两级单位（单位前带空格），万元以下两位小数；空值显示「—」
const fmtAmt = (v) => fmtCompact(v, { space: true })

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

// 紧凑日期时间（月日 时:分）
const fmtDt = (s) => fmtDateTime(s)

async function doDelete(batch) {
  const msg = batch.status === 'published'
    ? `确认删除已发布批次「${batch.business_unit} ${batch.year}年${batch.month}月 部门明细表」？\n删除后报表和图表将不再包含这部分数据。`
    : '确认删除此草稿批次？'
  if (!confirm(msg)) return
  try {
    await api.delete(`/batches/${batch.id}`)
    batches.value = batches.value.filter(b => b.id !== batch.id)
    await loadSubmissionStatus()
  } catch (e) { alert(e?.error || '删除失败') }
}

// Re-upload to replace an existing batch's period (entries can't be edited
// directly — publishing a new upload replaces the same BU+month+type).
function openReplace(batch) {
  upBu.value = batch.business_unit
  upYear.value = batch.year
  upMonth.value = batch.month
  uploadErr.value = ''
  uploadResult.value = null
  upFile.value = null
  previewTab.value = 'l1'
  showUpload.value = true
}

// ── Upload wizard ─────────────────────────────────────────────────────────────
function openUpload() {
  upBu.value = accessibleBus.value[0] || ''
  uploadErr.value = ''
  uploadResult.value = null
  upFile.value = null
  previewTab.value = 'l1'
  showUpload.value = true
}

// Derive the detected table type from the chosen file name for inline hinting
const detectedType = computed(() => {
  const n = upFile.value?.name?.toLowerCase() || ''
  if (n.endsWith('.xlsx') || n.endsWith('.json')) return { label: '部门明细表', cls: 'dept' }
  return null
})

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

// ── 未提交/未完整事业部统计（用于紧凑提示「N 个未提交」）──────────────────────
const statusRows = computed(() => submissionStatus.value?.bus || [])
const reminderItems = computed(() => statusRows.value.filter(r => !r.complete))

// ── 紧凑状态灯：红灯=未提交，绿灯=已提交，黄灯=草稿中 ────────────────────────
// 用于「月度提交状态」每个事业部，只展示 事业部 + 状态灯
function lightInfo(row) {
  const info = row?.department_detail
  const status = info?.status
  if (status === 'published') return { cls: 'light-green', label: '已提交' }
  if (status === 'draft')     return { cls: 'light-amber', label: '草稿中' }
  return { cls: 'light-red', label: '未提交' }
}

// 批次状态灯：已发布=绿灯(已提交)，草稿=红灯(未提交)
function batchLight(b) {
  return b.status === 'published'
    ? { cls: 'light-green', label: '已提交' }
    : { cls: 'light-red', label: '未提交' }
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
          上传金蝶部门明细表 · 核对利润指标 · 发布到报表
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

    <!-- ── Opt 8: 月度提交状态（紧凑：事业部 + 状态灯）─────────────────────── -->
    <div class="card compact-card" style="margin-bottom:12px">
      <div class="ss-head">
        <div class="section-title" style="margin:0">月度提交状态</div>
        <div class="ss-head-right">
          <!-- 红灯=未提交 的紧凑提示 -->
          <span v-if="!statusLoading && submissionStatus && statusRows.length" class="ss-summary">
            <span v-if="reminderItems.length" class="ss-summary-warn">
              <span class="light-dot light-red"></span>{{ reminderItems.length }} 个未提交
            </span>
            <span v-else class="ss-summary-ok">
              <span class="light-dot light-green"></span>全部已提交
            </span>
          </span>
          <select v-model="statusYear" class="sel-yr" @change="loadSubmissionStatus">
            <option v-for="y in years" :key="y" :value="y">{{ y }} 年</option>
          </select>
          <select v-model="statusMonth" class="sel-mo" @change="loadSubmissionStatus">
            <option v-for="m in months" :key="m" :value="m">{{ m }} 月</option>
          </select>
        </div>
      </div>

      <EmptyState v-if="statusLoading" loading style="padding:12px" />
      <EmptyState v-else-if="!submissionStatus || !submissionStatus.bus?.length" icon="📋" text="暂无提交数据" style="padding:12px" />
      <!-- 紧凑状态灯网格：每个事业部一格，红灯=未提交 -->
      <div v-else class="light-grid">
        <div
          v-for="row in submissionStatus.bus"
          :key="row.bu"
          class="light-cell"
          :title="row.bu + ' · ' + lightInfo(row).label"
        >
          <span class="light-dot" :class="lightInfo(row).cls"></span>
          <span class="light-bu">{{ row.bu }}</span>
        </div>
      </div>
    </div>

    <EmptyState v-if="loading" loading />
    <EmptyState v-else-if="loadErr" :error="loadErr" />

    <!-- Batch list — 紧凑行：事业部 + 状态灯（红灯=未提交）+ 操作 -->
    <div v-else class="card compact-card">
      <div class="ss-head">
        <div class="section-title" style="margin:0">导入批次</div>
        <span v-if="batches.length" class="ss-summary">共 {{ batches.length }} 个批次</span>
      </div>
      <div v-if="!batches.length" class="empty">
        <div class="icon">📂</div>
        <div>暂无导入记录</div>
        <div style="font-size:12px;color:var(--muted);margin-top:6px">上传金蝶导出的部门明细表，或使用KXT模板手动填报</div>
      </div>
      <div v-else class="batch-list">
        <div v-for="b in batches" :key="b.id" class="batch-row">
          <!-- 状态灯：红灯=未提交(草稿)，绿灯=已提交(已发布) -->
          <span class="light-dot" :class="batchLight(b).cls" :title="batchLight(b).label"></span>
          <!-- 事业部 -->
          <strong class="br-bu">{{ b.business_unit }}</strong>
          <!-- 状态文字 -->
          <span class="br-status" :class="b.status === 'published' ? 'st-ok' : 'st-no'">{{ batchLight(b).label }}</span>
          <!-- 次要信息：年月 · 类型 · 行数 -->
          <span class="br-meta">{{ b.year }}年{{ b.month }}月</span>
          <span class="br-meta br-type">{{ b.batch_type === 'profit_loss' ? '利润表' : '部门明细表' }}</span>
          <span class="br-meta br-dim">{{ b.row_count }} 行 · {{ b.uploaded_by || '-' }} · {{ fmtDt(b.published_at || b.uploaded_at) }}</span>
          <!-- 操作（紧凑） -->
          <span class="br-actions">
            <button v-if="b.status === 'draft' && auth.canPublish" class="btn btn-ghost btn-sm" @click="doPublish(b.id)">发布</button>
            <button v-if="b.status === 'published' && auth.canUpload" class="btn btn-ghost btn-sm" @click="openReplace(b)">替换</button>
            <button v-if="auth.canDelete" class="btn btn-danger btn-sm" @click="doDelete(b)">删除</button>
            <span v-if="b.status === 'published' && !auth.canUpload && !auth.canDelete" style="color:var(--muted);font-size:12px">—</span>
          </span>
        </div>
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

            <!-- Format guide -->
            <div class="fmt-guide">
              <div class="fg-card">
                <div class="fg-ico fg-xlsx">XLSX</div>
                <div>
                  <div class="fg-title">部门明细表</div>
                  <div class="fg-desc">金蝶核算维度明细账 .xlsx，或 KXT 模板（借/贷两列）</div>
                </div>
              </div>
            </div>

            <!-- Period selector row -->
            <div class="up-fields">
              <div class="form-row">
                <label>事业部 *</label>
                <select v-model="upBu">
                  <option value="">请选择</option>
                  <option v-for="bu in accessibleBus" :key="bu" :value="bu">{{ bu }}</option>
                </select>
              </div>
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

            <!-- 集团总部特殊口径提示：自动剔除财务金融部门 -->
            <div v-if="upBu === '集团总部'" class="hq-note">
              <span class="hq-note-icon">ℹ️</span>
              <span>集团总部口径：将<strong>自动剔除「财务金融」部门</strong>（供应链金融属独立业务条线，其收入/成本/费用均不计入集团总部报表）。</span>
            </div>

            <!-- File drop zone -->
            <label class="up-drop" :class="{ filled: upFile }">
              <input type="file" accept=".xlsx,.json" @change="e => upFile = e.target.files[0]" hidden />
              <template v-if="upFile">
                <span class="up-file-name">{{ upFile.name }}</span>
                <span v-if="detectedType" class="up-type-tag" :class="detectedType.cls">{{ detectedType.label }}</span>
              </template>
              <template v-else>
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                <span>点击选择部门明细表文件（.xlsx，或 .json 数组格式）</span>
              </template>
            </label>

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
                  <span v-if="uploadResult.fmt === 'kingdee_ledger'" class="badge badge-primary" style="margin-left:6px;font-size:10px">金蝶部门明细账</span>
                  <span v-else-if="uploadResult.fmt === 'kingdee'" class="badge badge-primary" style="margin-left:6px;font-size:10px">金蝶格式</span>
                  <span v-else-if="uploadResult.fmt === 'json'" class="badge badge-primary" style="margin-left:6px;font-size:10px">JSON格式</span>
                  <span v-else class="badge badge-muted" style="margin-left:6px;font-size:10px">KXT模板</span>
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

            <!-- ── 部门明细：推算利润指标 + 预览 ── -->
            <!-- ── 推算利润指标（由部门明细推算）── -->
            <div class="section-title" style="margin-bottom:10px">利润指标核对</div>
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
.modal-mask {
  position: fixed; inset: 0; z-index: 200;
  background: rgba(20,10,5,0.42); backdrop-filter: blur(8px);
  display: flex; align-items: center; justify-content: center; padding: 20px;
}
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

/* Format guide cards */
.fmt-guide { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 18px; }
@media (max-width: 560px) { .fmt-guide { grid-template-columns: 1fr; } }
.fg-card { display: flex; align-items: center; gap: 12px; padding: 12px 14px; border-radius: 12px; background: rgba(255,253,250,0.7); border: 1px solid var(--border); }
.fg-ico { flex-shrink: 0; width: 46px; height: 46px; border-radius: 10px; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 800; letter-spacing: 0.02em; color: #fff; }
.fg-xlsx { background: linear-gradient(135deg, #c96342, #e8855a); }
.fg-title { font-size: 14px; font-weight: 700; color: var(--text); }
.fg-desc { font-size: 12px; color: var(--muted); margin-top: 2px; }

/* Upload fields row */
.up-fields { display: grid; grid-template-columns: 1.4fr 1fr 1fr; gap: 12px; margin-bottom: 14px; }
@media (max-width: 560px) { .up-fields { grid-template-columns: 1fr; } }

/* File drop zone */
.up-drop {
  display: flex; align-items: center; justify-content: center; gap: 10px;
  padding: 22px 16px; border-radius: 12px; cursor: pointer;
  border: 1.5px dashed rgba(201,99,66,0.35); background: rgba(201,99,66,0.03);
  color: var(--muted); font-size: 13px; transition: all .18s; text-align: center;
}
.up-drop:hover { border-color: var(--primary); background: rgba(201,99,66,0.06); color: var(--primary); }
.up-drop.filled { border-style: solid; border-color: var(--primary); background: rgba(201,99,66,0.06); color: var(--text); }
.hq-note {
  display: flex; align-items: flex-start; gap: 7px;
  margin: 4px 0 12px; padding: 9px 12px; border-radius: 9px;
  background: rgba(21,101,192,0.07); border: 1px solid rgba(21,101,192,0.2);
  font-size: 12.5px; line-height: 1.55; color: #1257a8;
}
.hq-note-icon { flex-shrink: 0; }
.hq-note strong { color: #0d4789; }
.up-file-name { font-weight: 600; word-break: break-all; }
.up-type-tag { flex-shrink: 0; font-size: 11px; font-weight: 700; padding: 3px 10px; border-radius: 10px; color: #fff; }
.up-type-tag.pl { background: #1565c0; }
.up-type-tag.dept { background: var(--primary); }

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

/* ── 紧凑卡片 + 通用表头行 ───────────────────────────────────────────────── */
.compact-card { padding: 12px 14px; }
.ss-head {
  display: flex; align-items: center; justify-content: space-between;
  flex-wrap: wrap; gap: 8px; margin-bottom: 10px;
}
.ss-head-right { display: flex; gap: 8px; align-items: center; }
.ss-summary { font-size: 12px; color: var(--muted); display: inline-flex; align-items: center; gap: 6px; }
.ss-summary-warn { display: inline-flex; align-items: center; gap: 5px; color: #c62828; font-weight: 600; }
.ss-summary-ok { display: inline-flex; align-items: center; gap: 5px; color: #2e7d32; font-weight: 600; }

/* ── 状态灯（红=未提交 / 绿=已提交 / 黄=草稿中）─────────────────────────── */
.light-dot {
  width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0;
  display: inline-block;
}
.light-red   { background: #e53935; box-shadow: 0 0 0 3px rgba(229,57,53,0.16); }
.light-green { background: #2e7d32; box-shadow: 0 0 0 3px rgba(46,125,50,0.14); }
.light-amber { background: #f57f17; box-shadow: 0 0 0 3px rgba(245,127,23,0.16); }

/* 月度提交状态：紧凑事业部灯网格 */
.light-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(116px, 1fr));
  gap: 6px;
}
.light-cell {
  display: flex; align-items: center; gap: 7px;
  padding: 6px 10px; border-radius: 8px;
  border: 1px solid var(--border); background: rgba(255,253,250,0.6);
  font-size: 12.5px; min-width: 0;
}
.light-bu { font-weight: 600; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* ── 导入批次：紧凑行 ───────────────────────────────────────────────────── */
.batch-list { display: flex; flex-direction: column; }
.batch-row {
  display: flex; align-items: center; gap: 10px;
  padding: 7px 4px; border-bottom: 1px solid var(--border);
  min-height: 34px;
}
.batch-row:last-child { border-bottom: none; }
.batch-row:hover { background: rgba(201,99,66,0.035); }
.br-bu { font-size: 13.5px; flex-shrink: 0; }
.br-status { font-size: 12px; font-weight: 600; flex-shrink: 0; }
.br-status.st-ok { color: #2e7d32; }
.br-status.st-no { color: #c62828; }
.br-meta { font-size: 12px; color: var(--muted); flex-shrink: 0; }
.br-type {
  font-size: 10px; padding: 1px 7px; border-radius: 8px;
  background: rgba(0,0,0,0.05); color: var(--muted);
}
.br-dim { color: rgba(155,128,112,0.7); flex: 1; min-width: 0;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.br-actions { display: flex; gap: 6px; flex-shrink: 0; margin-left: auto; }
@media (max-width: 600px) {
  .br-meta:not(.br-dim) { display: none; }
  .br-dim { flex: 0 1 auto; }
}

</style>
