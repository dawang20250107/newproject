<script setup>
import { ref, computed, onMounted } from 'vue'
import { useCaiwuAuth } from '../../composables/useCaiwuAuth.js'
import { BUSINESS_UNITS, yearCST, lastMonthCST } from '../../constants.js'
import api from '../../api/caiwu.js'
import { fmtCompact } from '../../utils/format.js'
import EmptyState from '../../components/EmptyState.vue'

const auth = useCaiwuAuth()

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

onMounted(load)
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
        <label class="btn btn-ghost btn-sm" :class="{ disabled: uploading }" style="cursor:pointer">
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

    <template v-else-if="summary">
      <!-- 收入未按项目核算的提示 -->
      <div v-if="noProjectRevenue" class="pm-warn">
        ⚠ 本事业部 {{ year }}年{{ month }}月 <strong>收入未按项目核算</strong>（6001 全挂在「无」），
        无法做项目毛利分析。可忽略本事业部，或在金蝶让主营收入带上项目核算维度后重新导入。
      </div>

      <!-- KPI -->
      <div class="pm-kpis">
        <div class="pm-kpi">
          <div class="pm-k">项目数</div>
          <div class="pm-v">{{ summary.project_count }}</div>
        </div>
        <div class="pm-kpi">
          <div class="pm-k">收入合计</div>
          <div class="pm-v">{{ fmt(summary.total_revenue) }}</div>
        </div>
        <div class="pm-kpi">
          <div class="pm-k">成本合计</div>
          <div class="pm-v">{{ fmt(summary.total_cost) }}</div>
        </div>
        <div class="pm-kpi">
          <div class="pm-k">毛利合计</div>
          <div class="pm-v" :class="summary.total_margin >= 0 ? 'v-pos' : 'v-neg'">
            {{ summary.total_margin >= 0 ? '' : '' }}{{ fmt(summary.total_margin) }}
          </div>
        </div>
        <div class="pm-kpi">
          <div class="pm-k">毛利率</div>
          <div class="pm-v">{{ summary.margin_rate === null ? '—' : summary.margin_rate + '%' }}</div>
        </div>
        <div v-if="mode === 'direct' && summary.unalloc_cost" class="pm-kpi pm-kpi-pool">
          <div class="pm-k">未分摊成本池</div>
          <div class="pm-v">{{ fmt(summary.unalloc_cost) }}</div>
        </div>
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
              <tr v-if="!rows.length"><td colspan="6" class="empty-cell">暂无数据，请先导入「按项目核算明细账」</td></tr>
              <tr v-for="(r, i) in rows" :key="r.project_name">
                <td class="ctr text-muted">{{ i + 1 }}</td>
                <td class="fw">{{ r.project_name }}</td>
                <td class="amt">{{ fmt(r.revenue) }}</td>
                <td class="amt">{{ fmt(r.cost) }}</td>
                <td class="amt" :class="r.margin >= 0 ? 'text-ok' : 'text-danger'">{{ fmt(r.margin) }}</td>
                <td class="amt" :class="r.margin_rate !== null && r.margin_rate < 0 ? 'text-danger' : ''">
                  {{ r.margin_rate === null ? '—' : r.margin_rate + '%' }}
                </td>
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

.pm-kpis { display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; margin-bottom: 16px; }
@media (max-width: 900px) { .pm-kpis { grid-template-columns: repeat(3, 1fr); } }
.pm-kpi {
  background: rgba(255,255,255,0.78); border: 1px solid rgba(255,255,255,0.9);
  border-radius: 14px; padding: 12px 16px; box-shadow: 0 2px 14px rgba(0,0,0,0.05);
  border-left: 3px solid var(--border);
}
.pm-kpi-pool { border-left-color: #e65100; }
.pm-k { font-size: 11px; color: var(--muted); font-weight: 700; }
.pm-v { font-size: 21px; font-weight: 800; color: var(--text); margin-top: 4px; white-space: nowrap; }
.v-pos { color: #2e7d32; }
.v-neg { color: #c62828; }

.pm-table { width: 100%; font-size: 13px; }
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
