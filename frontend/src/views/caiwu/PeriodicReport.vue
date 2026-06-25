<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import ar from '../../api/ar.js'
import { downloadBlob } from '../../utils/download.js'
import { todayCST, yearCST, monthCST } from '../../constants.js'

const data = ref(null)
const loading = ref(false)
const err = ref('')
const exporting = ref(false)
const reportEl = ref(null)

// ── 期间控制 ──────────────────────────────────────────────────────────────
const periodType = ref('monthly')
const selYear = ref(yearCST())
const selMonth = ref(monthCST())
const selWeekIdx = ref(0)
const scopeValue = ref('')
const reviewer = ref('李亚琳')

const yearOptions = computed(() => {
  const y = yearCST(); return [y, y - 1, y - 2]
})

// 当月周列表（ISO 周一为周首）
const weekOptions = computed(() => {
  const y = selYear.value, m = selMonth.value
  const first = new Date(Date.UTC(y, m - 1, 1))
  const last = new Date(Date.UTC(y, m, 0))
  const weeks = []
  let cur = new Date(first)
  const dow = (cur.getUTCDay() + 6) % 7
  cur.setUTCDate(cur.getUTCDate() - dow)
  let guard = 0
  while (cur <= last && guard < 8) {
    const start = new Date(cur)
    const end = new Date(cur); end.setUTCDate(end.getUTCDate() + 6)
    if (end >= first && start <= last) {
      weeks.push({
        idx: weeks.length,
        start: start.toISOString().slice(0, 10),
        end: end.toISOString().slice(0, 10),
        label: `第${weeks.length + 1}周（${fmtMD(start)}~${fmtMD(end)}）`,
      })
    }
    cur.setUTCDate(cur.getUTCDate() + 7); guard++
  }
  return weeks
})
function fmtMD(d) { return `${d.getUTCMonth() + 1}/${d.getUTCDate()}` }

// ── 格式化 ────────────────────────────────────────────────────────────────
function wan(v) {
  const n = parseFloat(v)
  if (v == null || isNaN(n)) return '—'
  if (n === 0) return '0'
  if (Math.abs(n) >= 1e8) return (n / 1e8).toFixed(2) + '亿'
  return (n / 1e4).toFixed(1)
}
function rate(v) { return v == null ? '—' : v + '%' }
function rateClass(v, good = 100) {
  if (v == null) return ''
  return v >= good ? 'pos' : (v >= good * 0.7 ? 'mid' : 'neg')
}
function deltaTxt(v) { return v > 0 ? `+${v}` : (v < 0 ? `${v}` : '0') }

// ── 加载 ─────────────────────────────────────────────────────────────────
function buildParams() {
  const p = { period: periodType.value, reviewer: reviewer.value }
  if (scopeValue.value === 'group') p.scope = 'group'
  else if (scopeValue.value) p.dept = scopeValue.value
  if (periodType.value === 'weekly') {
    const w = weekOptions.value[selWeekIdx.value] || weekOptions.value[0]
    if (w) { p.start_date = w.start; p.end_date = w.end; p.week = w.idx + 1 }
    p.year = selYear.value; p.month = selMonth.value
  } else {
    p.year = selYear.value; p.month = selMonth.value
  }
  return p
}

async function load() {
  loading.value = true; err.value = ''
  try {
    const res = await ar.periodicReport(buildParams())
    data.value = res.data
    if (data.value?.meta) {
      reviewer.value = data.value.meta.reviewer
      if (!scopeValue.value) {
        scopeValue.value = data.value.meta.scope_kind === 'group' ? 'group' : data.value.meta.scope_name
      }
    }
  } catch (e) {
    err.value = e?.msg || '加载失败'
  } finally {
    loading.value = false
  }
}

const meta = computed(() => data.value?.meta)
const scopes = computed(() => data.value?.scopes_available || [])
const depts = computed(() => meta.value?.depts || [])
const isMulti = computed(() => meta.value?.is_multi)

function scopeRows(section) {
  if (!data.value) return []
  const rows = depts.value.map(d => ({ name: d, ...data.value[section].rows[d] }))
  if (isMulti.value) rows.push({ name: '合计', _total: true, ...data.value[section].total })
  return rows
}
const projRows = computed(() => scopeRows('projects'))
const arRows = computed(() => scopeRows('ar'))
const budRows = computed(() => scopeRows('budget'))
const cash = computed(() => data.value?.cash)

// ── 导出 ─────────────────────────────────────────────────────────────────
async function exportExcel() {
  exporting.value = true
  try {
    const blob = await ar.exportPeriodicReport(buildParams())
    downloadBlob(blob, `${meta.value.title}.xlsx`)
  } catch (e) {
    alert(e?.msg || '导出失败')
  } finally { exporting.value = false }
}

async function exportImage() {
  exporting.value = true
  try {
    const { default: html2canvas } = await import('html2canvas')
    await nextTick()
    const canvas = await html2canvas(reportEl.value, {
      scale: 2, backgroundColor: '#ffffff', useCORS: true, logging: false,
    })
    canvas.toBlob(blob => {
      if (blob) downloadBlob(blob, `${meta.value.title}.png`)
      exporting.value = false
    }, 'image/png')
  } catch (e) {
    alert('图片导出失败：' + (e?.message || e))
    exporting.value = false
  }
}

function onPeriodChange() {
  if (periodType.value === 'weekly' && selWeekIdx.value >= weekOptions.value.length) {
    selWeekIdx.value = 0
  }
  load()
}

onMounted(load)
</script>

<template>
  <div class="pr-wrap">
    <!-- ══ 控制栏 ══ -->
    <div class="pr-bar">
      <div class="seg">
        <button :class="{ on: periodType === 'monthly' }" @click="periodType = 'monthly'; onPeriodChange()">月报</button>
        <button :class="{ on: periodType === 'weekly' }" @click="periodType = 'weekly'; onPeriodChange()">周报</button>
      </div>

      <select v-model.number="selYear" class="pr-sel" @change="onPeriodChange">
        <option v-for="y in yearOptions" :key="y" :value="y">{{ y }}年</option>
      </select>
      <select v-model.number="selMonth" class="pr-sel" @change="onPeriodChange">
        <option v-for="m in 12" :key="m" :value="m">{{ m }}月</option>
      </select>
      <select v-if="periodType === 'weekly'" v-model.number="selWeekIdx" class="pr-sel wk" @change="load">
        <option v-for="w in weekOptions" :key="w.idx" :value="w.idx">{{ w.label }}</option>
      </select>

      <select v-if="scopes.length" v-model="scopeValue" class="pr-sel" @change="load">
        <option v-for="s in scopes" :key="s.value" :value="s.value">{{ s.label }}</option>
      </select>

      <div class="pr-bar-spacer"></div>

      <button class="pr-btn" :disabled="exporting || !data" @click="exportImage">导出图片</button>
      <button class="pr-btn accent" :disabled="exporting || !data" @click="exportExcel">导出 Excel</button>
    </div>

    <div v-if="loading && !data" class="pr-empty">报表生成中…</div>
    <div v-else-if="err" class="pr-empty err">{{ err }}</div>

    <!-- ══ 报告正文（可截图区）══ -->
    <div v-else-if="data" ref="reportEl" class="report">
      <!-- 报头 -->
      <div class="rp-head">
        <h1 class="rp-title">{{ meta.title }}</h1>
        <div class="rp-meta">
          <span>汇报人：<b>{{ meta.reporter }}</b></span>
          <span class="rp-div">|</span>
          <span>审核人：<input v-model="reviewer" class="rp-reviewer-input" /></span>
          <span class="rp-div">|</span>
          <span>汇报日期：<b>{{ meta.report_date }}</b></span>
          <span class="rp-div">|</span>
          <span>取值期间：<b>{{ meta.start_date }} ~ {{ meta.end_date }}</b></span>
        </div>
        <div class="rp-unit">金额单位：万元（比率除外）</div>
      </div>

      <!-- 一、项目规模 -->
      <section class="rp-sec">
        <div class="rp-sec-hd"><span class="rp-sec-num">（一）</span>项目规模<em>年初至今 · 项目台账口径</em></div>
        <table class="rp-tbl">
          <thead><tr>
            <th class="lft">事业部</th><th>在运项目</th><th>年初至今新签</th>
            <th>本期新签</th><th>较上期增减</th><th>项目总数</th>
          </tr></thead>
          <tbody>
            <tr v-for="r in projRows" :key="r.name" :class="{ tot: r._total }">
              <td class="lft">{{ r.name }}</td>
              <td>{{ r.active }}</td>
              <td>{{ r.ytd_new }}</td>
              <td>{{ r.period_new }}</td>
              <td><span class="dlt" :class="r.delta > 0 ? 'pos' : (r.delta < 0 ? 'neg' : '')">{{ deltaTxt(r.delta) }}</span></td>
              <td>{{ r.total }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <!-- 二、应收账款 -->
      <section class="rp-sec">
        <div class="rp-sec-hd"><span class="rp-sec-num">（二）</span>应收账款情况<em>资金运动表口径 · 期初+新增−回款±调整=期末</em></div>
        <table class="rp-tbl">
          <thead><tr>
            <th class="lft">事业部</th><th>期初未收</th><th>本期新增</th>
            <th>现金回款</th><th>非现金核销</th><th>账实差额</th>
            <th>期末未收</th><th>回款率</th>
          </tr></thead>
          <tbody>
            <tr v-for="r in arRows" :key="r.name" :class="{ tot: r._total }">
              <td class="lft">{{ r.name }}</td>
              <td>{{ wan(r.opening) }}</td>
              <td class="in">{{ wan(r.new_ar) }}</td>
              <td class="in">{{ wan(r.cash_in) }}</td>
              <td>{{ wan(r.noncash_in) }}</td>
              <td>{{ wan(r.adj_in) }}</td>
              <td class="strong">{{ wan(r.closing) }}</td>
              <td><span class="rt" :class="rateClass(r.collect_rate)">{{ rate(r.collect_rate) }}</span></td>
            </tr>
          </tbody>
        </table>
        <div class="rp-twin">
          <table class="rp-tbl mini">
            <thead><tr><th class="lft">期末账龄</th><th>逾期未收</th><th>未到期</th></tr></thead>
            <tbody>
              <tr v-for="r in arRows" :key="r.name" :class="{ tot: r._total }">
                <td class="lft">{{ r.name }}</td>
                <td class="neg">{{ wan(r.overdue) }}</td>
                <td>{{ wan(r.not_due) }}</td>
              </tr>
            </tbody>
          </table>
          <table class="rp-tbl mini">
            <thead><tr><th class="lft">本期到期</th><th>到期应收</th><th>到期已回</th><th>到期回款率</th></tr></thead>
            <tbody>
              <tr v-for="r in arRows" :key="r.name" :class="{ tot: r._total }">
                <td class="lft">{{ r.name }}</td>
                <td>{{ wan(r.due_amt) }}</td>
                <td class="in">{{ wan(r.due_collected) }}</td>
                <td><span class="rt" :class="rateClass(r.due_rate)">{{ rate(r.due_rate) }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- 三、应收预算 -->
      <section class="rp-sec">
        <div class="rp-sec-hd"><span class="rp-sec-num">（三）</span>应收预算完成<em>本期 + 年度累计</em></div>
        <table class="rp-tbl">
          <thead><tr>
            <th class="lft">事业部</th><th>本期预算</th><th>本期实际</th><th>本期完成率</th>
            <th>年度预算</th><th>年度实际</th><th>年度完成率</th>
          </tr></thead>
          <tbody>
            <tr v-for="r in budRows" :key="r.name" :class="{ tot: r._total }">
              <td class="lft">{{ r.name }}</td>
              <td>{{ wan(r.coll_budget) }}</td>
              <td class="in">{{ wan(r.coll_actual) }}</td>
              <td><span class="rt" :class="rateClass(r.coll_rate)">{{ rate(r.coll_rate) }}</span></td>
              <td>{{ wan(r.coll_budget_ytd) }}</td>
              <td class="in">{{ wan(r.coll_actual_ytd) }}</td>
              <td><span class="rt" :class="rateClass(r.coll_rate_ytd)">{{ rate(r.coll_rate_ytd) }}</span></td>
            </tr>
          </tbody>
        </table>
      </section>

      <!-- 四、应付预算 -->
      <section class="rp-sec">
        <div class="rp-sec-hd"><span class="rp-sec-num">（四）</span>应付预算完成<em>月度口径（付款预算按月维护）</em></div>
        <table class="rp-tbl">
          <thead><tr>
            <th class="lft">事业部</th><th>本月预算</th><th>本月实际</th><th>本月完成率</th>
            <th>年度预算</th><th>年度实际</th><th>年度完成率</th>
          </tr></thead>
          <tbody>
            <tr v-for="r in budRows" :key="r.name" :class="{ tot: r._total }">
              <td class="lft">{{ r.name }}</td>
              <td>{{ wan(r.pay_budget) }}</td>
              <td class="out">{{ wan(r.pay_actual) }}</td>
              <td><span class="rt" :class="rateClass(r.pay_rate)">{{ rate(r.pay_rate) }}</span></td>
              <td>{{ wan(r.pay_budget_ytd) }}</td>
              <td class="out">{{ wan(r.pay_actual_ytd) }}</td>
              <td><span class="rt" :class="rateClass(r.pay_rate_ytd)">{{ rate(r.pay_rate_ytd) }}</span></td>
            </tr>
          </tbody>
        </table>
      </section>

      <!-- 五、现金流 -->
      <section class="rp-sec" v-if="cash">
        <div class="rp-sec-hd"><span class="rp-sec-num">（五）</span>现金流情况<em>经营活动现金流 · 与现金流分析同口径</em></div>
        <table class="rp-tbl cash">
          <thead><tr><th class="lft">现金流项目</th><th>本期金额</th><th>本年累计</th></tr></thead>
          <tbody>
            <tr class="lv1"><td class="lft">一、经营活动现金流入</td><td class="in strong">{{ wan(cash.period.inflow) }}</td><td class="in strong">{{ wan(cash.ytd.inflow) }}</td></tr>
            <tr><td class="lft sub">　现金回款</td><td>{{ wan(cash.period.collected) }}</td><td>{{ wan(cash.ytd.collected) }}</td></tr>
            <tr><td class="lft sub">　预收款</td><td>{{ wan(cash.period.advance_received) }}</td><td>{{ wan(cash.ytd.advance_received) }}</td></tr>
            <tr class="lv1"><td class="lft">二、经营活动现金流出</td><td class="out strong">{{ wan(cash.period.outflow) }}</td><td class="out strong">{{ wan(cash.ytd.outflow) }}</td></tr>
            <tr><td class="lft sub">　实付款项（扣预付冲抵）</td><td>{{ wan(cash.period.paid) }}</td><td>{{ wan(cash.ytd.paid) }}</td></tr>
            <tr><td class="lft sub">　预付款</td><td>{{ wan(cash.period.advance_paid) }}</td><td>{{ wan(cash.ytd.advance_paid) }}</td></tr>
            <tr class="lv1 net"><td class="lft">三、经营活动净现金流</td>
              <td :class="cash.period.net >= 0 ? 'in strong' : 'neg strong'">{{ wan(cash.period.net) }}</td>
              <td :class="cash.ytd.net >= 0 ? 'in strong' : 'neg strong'">{{ wan(cash.ytd.net) }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <!-- 签字栏 -->
      <div class="rp-sign">
        <span>汇报人签字：<span class="rp-sign-line"></span></span>
        <span>审核人签字：<span class="rp-sign-line"></span></span>
        <span>签发日期：<span class="rp-sign-line"></span></span>
      </div>

      <div class="rp-foot">
        本报告由系统按取值期间自动生成，账面余额为存量口径，现金流为期间流量口径，所有金额以导出时点数据为准。
      </div>
    </div>
  </div>
</template>

<style scoped>
.pr-wrap { padding: 14px 0; }

/* ── 控制栏 ── */
.pr-bar {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  background: var(--surface-1); border: 1px solid var(--border-soft);
  border-radius: var(--radius); padding: 10px 14px; margin-bottom: 14px;
  box-shadow: var(--shadow-sm);
}
.pr-bar-spacer { flex: 1; }
.seg { display: inline-flex; border: 1px solid var(--border-strong); border-radius: var(--radius-xs); overflow: hidden; }
.seg button {
  border: none; background: transparent; padding: 6px 16px; font-size: 13px;
  font-weight: 700; color: var(--muted); cursor: pointer; transition: background .14s, color .14s;
}
.seg button + button { border-left: 1px solid var(--border); }
.seg button.on { background: var(--primary); color: #fff; }
.pr-sel {
  padding: 6px 10px; border: 1px solid var(--border-strong); border-radius: var(--radius-xs);
  font-size: 13px; background: var(--surface-1); color: var(--text); cursor: pointer;
}
.pr-sel.wk { min-width: 168px; }
.pr-sel:focus { outline: none; border-color: var(--primary); }
.pr-btn {
  padding: 7px 15px; border: 1px solid var(--border-strong); border-radius: var(--radius-xs);
  background: var(--surface-tint); font-size: 13px; font-weight: 600; color: var(--text-2);
  cursor: pointer; transition: border-color .14s, color .14s; white-space: nowrap;
}
.pr-btn:hover:not(:disabled) { border-color: var(--primary); color: var(--primary); }
.pr-btn.accent { background: var(--primary); color: #fff; border-color: var(--primary); }
.pr-btn.accent:hover:not(:disabled) { opacity: .88; }
.pr-btn:disabled { opacity: .5; cursor: not-allowed; }

.pr-empty { text-align: center; padding: 60px; color: var(--muted); }
.pr-empty.err { color: var(--c-danger); }

/* ── 报告正文 ── */
.report {
  background: #fff; border: 1px solid #ddd;
  padding: 32px 38px 28px; max-width: 1080px; margin: 0 auto;
  box-shadow: 0 2px 8px rgba(0,0,0,.08);
}

/* 报头 */
.rp-head {
  text-align: center; padding-bottom: 16px;
  border-bottom: 2px solid #1a1a1a; margin-bottom: 24px;
}
.rp-title { font-size: 22px; font-weight: 900; color: #1a1a1a; letter-spacing: 2px; margin: 0 0 12px; }
.rp-meta { display: flex; justify-content: center; flex-wrap: wrap; gap: 8px; font-size: 12.5px; color: #555; }
.rp-meta b { color: #1a1a1a; font-weight: 700; }
.rp-div { color: #bbb; }
.rp-unit { font-size: 11.5px; color: #888; margin-top: 8px; }

/* 审核人内联编辑 */
.rp-reviewer-input {
  border: none; border-bottom: 1px dashed #bbb; background: transparent;
  font-size: 12.5px; font-weight: 700; color: #1a1a1a;
  width: 72px; padding: 0 2px; outline: none; font-family: inherit;
}
.rp-reviewer-input:focus { border-bottom-color: var(--primary); }

/* 分区标题 */
.rp-sec { margin-bottom: 24px; }
.rp-sec-hd {
  display: flex; align-items: baseline; gap: 4px; font-size: 14px; font-weight: 800;
  color: #1a1a1a; padding: 6px 0; margin-bottom: 10px; border-bottom: 1px solid #d0d0d0;
}
.rp-sec-num { font-weight: 800; }
.rp-sec-hd em { font-style: normal; font-size: 11.5px; font-weight: 400; color: #888; margin-left: 8px; }

/* 表格：精简 Excel 风格 */
.rp-tbl { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; }
.rp-tbl th {
  background: #f0f0f0; color: #333; font-weight: 700; padding: 8px 10px;
  text-align: right; border: 1px solid #ccc; white-space: nowrap;
}
.rp-tbl th.lft { text-align: left; }
.rp-tbl td { padding: 7px 10px; text-align: right; border: 1px solid #e0e0e0; color: #1a1a1a; }
.rp-tbl td.lft { text-align: left; font-weight: 600; color: #333; }
.rp-tbl tbody tr:hover { background: #fafafa; }
.rp-tbl tr.tot td { background: #ebebeb; font-weight: 800; border-top: 2px solid #aaa; }
.rp-tbl td.in { color: #0a7a4a; }
.rp-tbl td.out { color: #b00020; }
.rp-tbl td.neg { color: #b00020; }
.rp-tbl td.strong { font-weight: 800; }

.dlt { font-weight: 700; }
.dlt.pos { color: #0a7a4a; } .dlt.neg { color: #b00020; }
.rt { font-weight: 700; padding: 1px 6px; border-radius: 2px; font-size: 11.5px; }
.rt.pos { color: #0a7a4a; background: #e6f4ee; }
.rt.mid { color: #a05a00; background: #fef3e2; }
.rt.neg { color: #b00020; background: #fde8eb; }

.rp-twin { display: grid; grid-template-columns: 1fr 1.3fr; gap: 14px; margin-top: 12px; }
.rp-tbl.mini th, .rp-tbl.mini td { padding: 6px 9px; font-size: 12px; }

/* 现金流表 */
.rp-tbl.cash td.lft { font-weight: 600; }
.rp-tbl.cash td.lft.sub { font-weight: 400; color: #555; }
.rp-tbl.cash tr.lv1 td { background: #f0f0f0; font-weight: 800; }
.rp-tbl.cash tr.net td { border-top: 2px solid #333; background: #f5f5f5; font-size: 13px; font-weight: 800; }

/* 签字栏 */
.rp-sign {
  display: flex; gap: 40px; justify-content: flex-end;
  padding: 20px 0 8px; font-size: 12.5px; color: #555;
  border-top: 1px solid #e0e0e0; margin-top: 16px;
}
.rp-sign-line {
  display: inline-block; width: 80px; border-bottom: 1px solid #999;
  margin-left: 4px; vertical-align: bottom;
}

/* 备注行 */
.rp-foot { font-size: 11px; color: #999; line-height: 1.7; padding-top: 12px; }

@media (max-width: 768px) {
  .report { padding: 18px 14px; }
  .rp-twin { grid-template-columns: 1fr; }
  .rp-meta { font-size: 11px; }
  .rp-sign { flex-wrap: wrap; gap: 16px; justify-content: flex-start; }
}
</style>
