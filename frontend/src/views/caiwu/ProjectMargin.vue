<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useCaiwuAuth } from '../../composables/useCaiwuAuth.js'
import { BUSINESS_UNITS, yearCST, lastMonthCST } from '../../constants.js'
import api from '../../api/caiwu.js'
import { fmtCompact } from '../../utils/format.js'
import EmptyState from '../../components/EmptyState.vue'

const auth = useCaiwuAuth()
const route = useRoute()

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
    <div class="topbar">
      <div>
        <h1>项目毛利</h1>
        <div style="font-size:13px;color:var(--muted);margin-top:2px">
          业财融合 · 金蝶「按项目核算明细账」→ 项目级 收入 / 成本 / 毛利
        </div>
      </div>
      <div style="display:flex;gap:8px">
        <label v-if="auth.canUpload" class="btn btn-ghost btn-sm" :class="{ disabled: uploading }" style="cursor:pointer">
          {{ uploading ? '导入中…' : '↑ 导入项目核算账' }}
          <input ref="fileInput" type="file" accept=".xlsx,.xls" style="display:none" @change="onPickFile" />
        </label>
      </div>
    </div>

    <!-- Filter bar -->
    <div class="pm-filterbar">
      <select v-model="bu" class="pm-sel" @change="load">
        <option v-for="b in accessibleBus" :key="b" :value="b">{{ b }}</option>
      </select>
      <select v-model.number="year" class="pm-sel" @change="load">
        <option v-for="y in years" :key="y" :value="y">{{ y }} 年</option>
      </select>
      <select v-model.number="month" class="pm-sel" @change="load">
        <option v-for="m in months" :key="m" :value="m">{{ m }} 月</option>
      </select>
      <div class="pm-modes">
        <button :class="['pm-mode', mode === 'direct' ? 'on' : '']"
                @click="mode = 'direct'; load()">直接口径</button>
        <button :class="['pm-mode', mode === 'allocated' ? 'on' : '']"
                @click="mode = 'allocated'; load()">分摊口径</button>
      </div>
      <span class="pm-mode-hint">
        {{ mode === 'direct' ? '未挂项目成本单列为「未分摊池」' : '未挂成本按各项目收入比例分摊' }}
      </span>
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
      <div class="card">
        <div class="section-title">
          项目毛利明细
          <span class="section-sub">{{ bu }} · {{ year }}年{{ month }}月 · {{ mode === 'direct' ? '直接口径' : '分摊口径' }}</span>
        </div>
        <div class="table-wrap">
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
              <tr v-for="(r, i) in rows" :key="r.project_name">
                <td class="ctr text-muted">{{ i + 1 }}</td>
                <td class="fw pm-name" :title="r.project_name">{{ r.project_name }}</td>
                <td class="amt">{{ fmt(r.revenue) }}</td>
                <td class="amt">{{ fmt(r.cost) }}</td>
                <td class="amt" :class="r.margin >= 0 ? 'text-ok' : 'text-danger'">{{ fmt(r.margin) }}</td>
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
                <td class="amt fw" :class="summary.total_margin >= 0 ? 'text-ok' : 'text-danger'">{{ fmt(summary.total_margin) }}</td>
                <td class="amt fw">{{ summary.margin_rate === null ? '—' : summary.margin_rate + '%' }}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>
    </template>

    <!-- 吸底汇总：对齐付款台账的 bottom-bar -->
    <Teleport to="body">
      <div v-if="summary && summary.has_data" class="bottom-bar">
        <div class="bb-summary">
          <span class="bb-item"><i>项目数</i><b>{{ summary.project_count }}</b></span>
          <span class="bb-item"><i>收入合计</i><b>{{ fmt(summary.total_revenue) }}</b></span>
          <span class="bb-item"><i>成本合计</i><b>{{ fmt(summary.total_cost) }}</b></span>
          <span class="bb-item" :class="summary.total_margin >= 0 ? 'ok' : 'warn'"><i>毛利合计</i><b>{{ fmt(summary.total_margin) }}</b></span>
          <span class="bb-item"><i>毛利率</i><b>{{ summary.margin_rate === null ? '—' : summary.margin_rate + '%' }}</b></span>
          <span v-if="mode === 'direct' && summary.unalloc_cost" class="bb-item"><i>未分摊池</i><b>{{ fmt(summary.unalloc_cost) }}</b></span>
        </div>
        <div class="bb-pager">
          <span class="page-info">{{ bu }} · {{ year }}年{{ month }}月 · {{ mode === 'direct' ? '直接口径' : '分摊口径' }}</span>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.pm-filterbar {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  background: rgba(255,255,255,0.88); border: 1px solid rgba(255,255,255,0.92);
  border-radius: 14px; padding: 8px 12px; box-shadow: 0 2px 14px rgba(0,0,0,0.06);
  margin-bottom: 18px;
}
.pm-sel {
  height: 32px; padding: 0 10px; border: none; background: rgba(0,0,0,0.04);
  border-radius: 8px; font-size: 13px; color: var(--text); cursor: pointer; outline: none;
}
.pm-sel:hover, .pm-sel:focus { background: rgba(201,99,66,0.09); color: var(--primary); }
.pm-modes { display: inline-flex; background: rgba(0,0,0,0.05); border-radius: 9px; padding: 3px; }
.pm-mode { border: none; background: none; padding: 5px 14px; border-radius: 7px; font-size: 12.5px; color: var(--muted); cursor: pointer; }
.pm-mode.on { background: #fff; color: var(--primary); font-weight: 700; box-shadow: 0 1px 4px rgba(0,0,0,0.1); }
.pm-mode-hint { font-size: 11.5px; color: var(--muted); }

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

.pm-table { width: 100%; font-size: 13px; }
.pm-table th.ctr, .pm-table td.ctr { width: 44px; }
.pm-name { max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pm-pool-row td { background: rgba(230,81,0,0.04); color: var(--muted); }
.pm-table thead th { padding: 9px 12px; font-size: 11.5px; color: var(--muted); font-weight: 700; border-bottom: 1px solid rgba(0,0,0,0.08); }
.pm-table tbody td { padding: 9px 12px; border-bottom: 1px solid rgba(0,0,0,0.04); }
.pm-table tbody tr:hover { background: rgba(201,99,66,0.03); }
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
