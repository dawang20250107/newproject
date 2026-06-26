<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useCaiwuAuth } from '../../composables/useCaiwuAuth.js'
import { BUSINESS_UNITS, yearCST, lastMonthCST } from '../../constants.js'
import api from '../../api/caiwu.js'
import { fmtCompact } from '../../utils/format.js'
import EmptyState from '../../components/EmptyState.vue'
import ProjectPnlCard from './ProjectPnlCard.vue'
import ContextMenu from '../../components/ContextMenu.vue'
import { useContextMenu } from '../../composables/useContextMenu.js'
import { copyText, copyRowTSV } from '../../utils/clipboard.js'
import { useToast } from '../../composables/useToast.js'

const auth = useCaiwuAuth()
const route = useRoute()
const toast = useToast()

const years = Array.from({ length: 5 }, (_, i) => yearCST() - 2 + i)
const months = Array.from({ length: 12 }, (_, i) => i + 1)
const accessibleBus = computed(() => {
  if (auth.isAdmin) return BUSINESS_UNITS
  return (auth.user?.departments || []).filter(d => BUSINESS_UNITS.includes(d))
})

const bu = ref(accessibleBus.value[0] || '')
const year = ref(lastMonthCST().year)
const month = ref(lastMonthCST().month)
const mode = ref('direct')   // 'direct' | 'allocated'

const data = ref(null)
const loading = ref(false)
const loadErr = ref('')

const fmt = (v) => fmtCompact(v, { space: true })

// ── 右键上下文菜单 ────────────────────────────────────────────────────────────
const pnlTarget = ref(null)
function openPnl(r) {
  if (!r?.project_name) return
  pnlTarget.value = { name: r.project_name, year: year.value }
}
const ctx = useContextMenu()
const ROW_COPY_COLS = [
  { key: 'project_name', label: '项目' },
  { key: 'revenue', label: '收入', format: v => fmt(v) },
  { key: 'cost', label: '成本', format: v => fmt(v) },
  { key: 'margin', label: '毛利', format: v => fmt(v) },
  { key: 'margin_rate', label: '毛利率', format: v => (v === null ? '' : v + '%') },
]
async function copyField(val, label) {
  const ok = await copyText(val)
  ok ? toast.success(`已复制：${label}`) : toast.error('复制失败')
}
async function copyWholeRow(r) {
  const ok = await copyRowTSV(r, ROW_COPY_COLS, { header: true })
  ok ? toast.success('已复制整行（含表头，可粘贴到 Excel）') : toast.error('复制失败')
}
const ctxItems = computed(() => {
  const r = ctx.menu.payload
  if (!r) return []
  return [
    { key: 'pnl', label: '查看业财损益卡', icon: 'chart', action: row => openPnl(row) },
    { divider: true },
    {
      key: 'copy', label: '复制', icon: 'copy',
      children: [
        { key: 'copy-row', label: '复制整行', icon: 'copy', shortcut: '⌘C', action: row => copyWholeRow(row) },
        { divider: true },
        { key: 'copy-name', label: '项目名称', icon: 'cell', action: row => copyField(row.project_name, row.project_name) },
        { key: 'copy-margin', label: '毛利', icon: 'cell', action: row => copyField(fmt(row.margin), fmt(row.margin)) },
      ],
    },
  ]
})

const rows = computed(() => data.value?.rows || [])
const summary = computed(() => data.value?.summary || null)
const noProjectRevenue = computed(() =>
  summary.value && summary.value.has_data && !summary.value.revenue_by_project)
const noData = computed(() => summary.value && !summary.value.has_data)
// 直接口径下把「未挂项目」作为一行加入表格，使各列与合计对得上
const showPool = computed(() =>
  data.value?.mode === 'direct' && summary.value &&
  (summary.value.unalloc_cost || summary.value.unalloc_revenue))
// 对账提示：项目台账收入与同期已发布报表主营业务收入偏差超过 1 元时提示
const reconDiff = computed(() => {
  const s = summary.value
  if (!s || s.report_revenue === null || s.report_revenue === undefined) return null
  return Math.abs(s.revenue_diff || 0) > 1 ? s.revenue_diff : null
})

async function load() {
  if (!bu.value) return
  loading.value = true
  loadErr.value = ''
  try {
    const res = await api.get('/project-margin', {
      params: { bu: bu.value, year: year.value, month: month.value, mode: mode.value },
    })
    data.value = res.data
  } catch (e) {
    loadErr.value = e?.msg || '加载失败'
    data.value = null
  } finally { loading.value = false }
}

// Upload
const fileInput = ref(null)
const uploading = ref(false)
async function onPickFile(e) {
  const file = e.target.files?.[0]
  if (!file) return
  if (uploading.value) { e.target.value = ''; return }
  if (!bu.value) { alert('请先选择事业部'); e.target.value = ''; return }
  uploading.value = true
  try {
    const fd = new FormData()
    fd.append('bu', bu.value)
    fd.append('year', year.value)
    fd.append('month', month.value)
    fd.append('file', file)
    const res = await api.post('/project-margin/upload', fd,
      { headers: { 'Content-Type': 'multipart/form-data' } })
    alert(`导入成功：${bu.value} ${year.value}年${month.value}月，共 ${res.data.project_count} 个项目`)
    await load()
  } catch (err) {
    alert(err?.msg || '导入失败')
  } finally { uploading.value = false; e.target.value = '' }
}

onMounted(() => {
  // 支持从驾驶舱对话「下钻」带入事业部 / 期间
  const qb = route.query.bu, qy = +route.query.year, qm = +route.query.month
  if (qb && accessibleBus.value.includes(qb)) bu.value = qb
  if (qy >= 2000 && qy <= 2100) year.value = qy
  if (qm >= 1 && qm <= 12) month.value = qm
  load()
})
</script>

<template>
  <div>
    <!-- 标题行：标题居左，筛选项全部并入同一行靠右，去掉独立的整行筛选框 -->
    <div class="topbar pm-topbar">
      <h1>项目毛利</h1>
      <div class="pm-controls">
        <select v-model="bu" class="pm-sel" @change="load">
          <option v-for="b in accessibleBus" :key="b" :value="b">{{ b }}</option>
        </select>
        <select v-model.number="year" class="pm-sel" @change="load">
          <option v-for="y in years" :key="y" :value="y">{{ y }} 年</option>
        </select>
        <select v-model.number="month" class="pm-sel" @change="load">
          <option v-for="m in months" :key="m" :value="m">{{ m }} 月</option>
        </select>
        <div class="pm-modes" :title="mode === 'direct' ? '未挂项目成本单列为「未分摊池」' : '未挂成本按各项目收入比例分摊'">
          <button :class="['pm-mode', mode === 'direct' ? 'on' : '']"
                  @click="mode = 'direct'; load()">直接口径</button>
          <button :class="['pm-mode', mode === 'allocated' ? 'on' : '']"
                  @click="mode = 'allocated'; load()">分摊口径</button>
        </div>
        <label v-if="auth.canUpload" class="btn btn-ghost btn-sm" :class="{ disabled: uploading }" style="cursor:pointer">
          {{ uploading ? '导入中…' : '↑ 导入' }}
          <input ref="fileInput" type="file" accept=".xlsx,.xls" style="display:none" @change="onPickFile" />
        </label>
      </div>
    </div>

    <EmptyState v-if="loading && !data" loading />
    <EmptyState v-else-if="loadErr" :error="loadErr" />

    <!-- 本期从未导入项目核算账 -->
    <div v-else-if="noData" class="pm-emptybox">
      <div class="pm-empty-ico">📊</div>
      <div class="pm-empty-title">{{ bu }} · {{ year }}年{{ month }}月 暂无项目核算数据</div>
      <div class="pm-empty-sub">导入金蝶「核算维度明细账（按项目）」后，即可查看项目级收入 / 成本 / 毛利</div>
      <label v-if="auth.canUpload" class="btn btn-primary btn-sm" :class="{ disabled: uploading }" style="cursor:pointer;margin-top:14px">
        {{ uploading ? '导入中…' : '↑ 导入项目核算账' }}
        <input type="file" accept=".xlsx,.xls" style="display:none" @change="onPickFile" />
      </label>
    </div>

    <template v-else-if="summary">
      <!-- 收入未按项目核算的提示 -->
      <div v-if="noProjectRevenue" class="pm-warn">
        ⚠ 本事业部 {{ year }}年{{ month }}月 <strong>收入未按项目核算</strong>（6001 全挂在「无」），
        无法做项目毛利分析。可忽略本事业部，或在金蝶让主营收入带上项目核算维度后重新导入。
      </div>

      <!-- 项目台账 ↔ 报表收入对账提示 -->
      <div v-if="reconDiff !== null" class="pm-warn">
        ⚠ 项目台账收入合计与同期已发布报表的主营业务收入
        <strong>相差 {{ fmt(reconDiff) }}</strong>
        （报表 {{ fmt(summary.report_revenue) }}）。两边取数账簿不同允许有差，
        但持续偏大通常意味着部分收入未挂项目维度或导入期间不一致，请核对。
      </div>

      <!-- Table -->
      <div class="card fh-fill">
        <div class="section-title">
          项目毛利明细
          <span class="section-sub">{{ bu }} · {{ year }}年{{ month }}月 · {{ mode === 'direct' ? '直接口径' : '分摊口径' }}</span>
        </div>
        <div class="table-wrap page-scroll">
          <table class="pm-table">
            <thead>
              <tr>
                <th class="ctr">#</th>
                <th>项目 / 客户</th>
                <th class="amt">收入</th>
                <th class="amt">主营成本</th>
                <th class="amt">毛利</th>
                <th class="amt">毛利率</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!rows.length && !showPool"><td colspan="6" class="empty-cell">本事业部本期无已挂项目的数据</td></tr>
              <tr v-for="(r, i) in rows" :key="r.project_name" class="pm-row" @click="openPnl(r)" @contextmenu.prevent="ctx.open($event, r)">
                <td class="ctr text-muted">{{ i + 1 }}</td>
                <td class="fw pm-name" :title="r.project_name">{{ r.project_name }}<span class="pm-drill">损益 ›</span></td>
                <td class="amt">{{ fmt(r.revenue) }}</td>
                <td class="amt">{{ fmt(r.cost) }}</td>
                <td class="amt" :class="r.margin >= 0 ? 'text-ok' : 'text-danger'"><span class="caret">{{ r.margin >= 0 ? '▲' : '▼' }}</span>{{ fmt(r.margin) }}</td>
                <td class="amt" :class="r.margin_rate !== null && r.margin_rate < 0 ? 'text-danger' : ''">
                  {{ r.margin_rate === null ? '—' : r.margin_rate + '%' }}
                </td>
              </tr>
              <!-- 直接口径：未挂项目池单列一行，使各列与合计对齐 -->
              <tr v-if="showPool" class="pm-pool-row">
                <td class="ctr text-muted">—</td>
                <td class="fw">（未挂项目 · 未分摊池）</td>
                <td class="amt">{{ fmt(summary.unalloc_revenue) }}</td>
                <td class="amt">{{ fmt(summary.unalloc_cost) }}</td>
                <td class="amt text-muted">{{ fmt(summary.unalloc_revenue - summary.unalloc_cost) }}</td>
                <td class="amt text-muted">—</td>
              </tr>
            </tbody>
            <tfoot v-if="rows.length">
              <tr class="pm-foot">
                <td></td>
                <td class="fw">合计（{{ summary.project_count }} 个项目<span v-if="mode==='direct' && summary.unalloc_cost"> + 未分摊池</span>）</td>
                <td class="amt fw">{{ fmt(summary.total_revenue) }}</td>
                <td class="amt fw">{{ fmt(summary.total_cost) }}</td>
                <td class="amt fw" :class="summary.total_margin >= 0 ? 'text-ok' : 'text-danger'"><span class="caret">{{ summary.total_margin >= 0 ? '▲' : '▼' }}</span>{{ fmt(summary.total_margin) }}</td>
                <td class="amt fw">{{ summary.margin_rate === null ? '—' : summary.margin_rate + '%' }}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>
    </template>

    <!-- 吸底汇总：对齐付款管理的 bottom-bar -->
    <Teleport to="body">
      <div v-if="summary && summary.has_data" class="bottom-bar">
        <div class="bb-summary">
          <span class="bb-item">
            <svg class="bb-ico" viewBox="0 0 24 24" fill="none" stroke="#9b8070" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l8 4-8 4-8-4 8-4z"/><path d="M4 12l8 4 8-4"/></svg>
            <i>项目数</i><b>{{ summary.project_count }}</b></span>
          <span class="bb-item">
            <svg class="bb-ico" viewBox="0 0 24 24" fill="none" stroke="#2e7d32" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4v11"/><path d="M7 10l5 5 5-5"/><path d="M5 20h14"/></svg>
            <i>收入合计</i><b>{{ fmt(summary.total_revenue) }}</b></span>
          <span class="bb-item">
            <svg class="bb-ico" viewBox="0 0 24 24" fill="none" stroke="#c62828" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20V9"/><path d="M7 14l5-5 5 5"/><path d="M5 4h14"/></svg>
            <i>成本合计</i><b>{{ fmt(summary.total_cost) }}</b></span>
          <span class="bb-item" :class="summary.total_margin >= 0 ? 'ok' : 'warn'">
            <svg class="bb-ico" viewBox="0 0 24 24" fill="none" stroke="#7a614c" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="6" width="18" height="13" rx="2"/><path d="M3 10.5h18"/></svg>
            <i>毛利合计</i><b>{{ fmt(summary.total_margin) }}</b></span>
          <span class="bb-item">
            <svg class="bb-ico" viewBox="0 0 24 24" fill="none" stroke="#9b8070" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="7" cy="7" r="2.4"/><circle cx="17" cy="17" r="2.4"/><path d="M18 6L6 18"/></svg>
            <i>毛利率</i><b>{{ summary.margin_rate === null ? '—' : summary.margin_rate + '%' }}</b></span>
          <span v-if="mode === 'direct' && summary.unalloc_cost" class="bb-item">
            <svg class="bb-ico" viewBox="0 0 24 24" fill="none" stroke="#e65100" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l9 16H3z"/><path d="M12 10v4"/><path d="M12 17h.01"/></svg>
            <i>未分摊池</i><b>{{ fmt(summary.unalloc_cost) }}</b></span>
        </div>
        <div class="bb-pager">
          <span class="page-info">{{ bu }} · {{ year }}年{{ month }}月 · {{ mode === 'direct' ? '直接口径' : '分摊口径' }}</span>
        </div>
      </div>
    </Teleport>

    <!-- 业财损益卡 -->
    <ProjectPnlCard v-if="pnlTarget" :name="pnlTarget.name" :year="pnlTarget.year" :askable="false" @close="pnlTarget = null" />

    <!-- 右键上下文菜单 -->
    <ContextMenu :ctx="ctx" :items="ctxItems" />
  </div>
</template>

<style scoped>
/* 筛选项并入标题行靠右，去掉独立整行筛选框 */
.pm-topbar { gap: 12px; flex-wrap: wrap; }
.pm-controls { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.pm-sel {
  width: auto; height: 32px; padding: 0 10px; border: 1px solid var(--border); background: rgba(255,255,255,0.6);
  border-radius: 8px; font-size: 13px; color: var(--text); cursor: pointer; outline: none;
}
.pm-sel:hover, .pm-sel:focus { background: rgba(201,99,66,0.09); color: var(--primary); }
.pm-modes { display: inline-flex; background: rgba(0,0,0,0.05); border-radius: 9px; padding: 3px; }
.pm-mode { border: none; background: none; padding: 5px 14px; border-radius: 7px; font-size: 12.5px; color: var(--muted); cursor: pointer; }
.pm-mode.on { background: #fff; color: var(--primary); font-weight: 700; box-shadow: 0 1px 4px rgba(0,0,0,0.1); }

.pm-warn {
  background: rgba(245,127,23,0.08); border: 1px solid rgba(245,127,23,0.3);
  border-radius: 12px; padding: 12px 16px; margin-bottom: 16px; font-size: 13px; color: #b45309;
}

.pm-emptybox {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  text-align: center; padding: 56px 20px;
  background: rgba(255,255,255,0.6); border: 1px dashed rgba(0,0,0,0.12); border-radius: 16px;
}
.pm-empty-ico { font-size: 40px; margin-bottom: 10px; opacity: .85; }
.pm-empty-title { font-size: 15px; font-weight: 700; color: var(--text); }
.pm-empty-sub { font-size: 12.5px; color: var(--muted); margin-top: 6px; max-width: 420px; line-height: 1.6; }

/* 固定视口：表头吸顶 + 为吸底栏预留空间 */
.fh-fill { padding-bottom: 40px; }
.table-wrap thead th { position: sticky; top: 0; z-index: 5; background: #f4f1ef; }

.pm-table { width: 100%; font-size: 13px; }
.pm-table th.ctr, .pm-table td.ctr { width: 44px; }
.pm-name { max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pm-row { cursor: pointer; }
.pm-row:hover { background: rgba(201,99,66,0.045); }
.pm-drill { margin-left: 6px; font-size: 11px; color: var(--primary); opacity: 0; transition: opacity .12s; }
.pm-row:hover .pm-drill { opacity: .75; }
.pm-pool-row td { background: rgba(230,81,0,0.04); color: var(--muted); }
.pm-table thead th { padding: 9px 12px; font-size: 11.5px; color: var(--muted); font-weight: 700; border-bottom: 1px solid rgba(0,0,0,0.08); }
.pm-table tbody td { padding: 9px 12px; border-bottom: 1px solid rgba(0,0,0,0.04); }
.caret { font-size: 8px; margin-right: 3px; vertical-align: 1px; opacity: .85; }
.bb-ico { width: 13px; height: 13px; align-self: center; flex-shrink: 0; }
/* 极淡斑马纹 + hover（hover 置后，保证任意行可见悬停反馈） */
.pm-table tbody tr:nth-child(even) td { background: rgba(255,255,255,0.20); }
.pm-table tbody tr.pm-pool-row td { background: rgba(230,81,0,0.05); }
.pm-table tbody tr:hover td { background: rgba(201,99,66,0.07); }
.pm-table tbody tr.pm-pool-row:hover td { background: rgba(230,81,0,0.06); }
.pm-foot td { padding: 10px 12px; border-top: 2px solid rgba(201,99,66,0.3); background: #f8efeb; font-variant-numeric: tabular-nums; }
.amt { text-align: right; font-variant-numeric: tabular-nums; }
.ctr { text-align: center; }
.fw { font-weight: 600; }
.text-ok { color: #2e7d32; font-weight: 600; }
.text-danger { color: #c62828; font-weight: 600; }
.text-muted { color: var(--muted); }
.empty-cell { text-align: center; padding: 36px !important; color: var(--muted); }
.section-sub { font-size: 11px; color: var(--muted); font-weight: 400; margin-left: 8px; }
</style>
