<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import api from '../../api/caiwu.js'
import { useCaiwuAuth } from '../../composables/useCaiwuAuth.js'
import { useToast } from '../../composables/useToast.js'
import { confirmDlg } from '../../composables/confirm.js'
import { fmtMoney, fmtCompact } from '../../utils/format.js'
import EmptyState from '../../components/EmptyState.vue'

const auth = useCaiwuAuth()
const toast = useToast()

// ── 期间（CST 口径，与全站一致）──────────────────────────────────────────────
const now = new Date(Date.now() + 8 * 3600 * 1000)
const year = ref(now.getUTCMonth() === 0 ? now.getUTCFullYear() - 1 : now.getUTCFullYear())
const month = ref(now.getUTCMonth() === 0 ? 12 : now.getUTCMonth())   // 默认上一个已结账月
const YEARS = Array.from({ length: 6 }, (_, i) => now.getUTCFullYear() - 4 + i)

// ── 数据 ────────────────────────────────────────────────────────────────────
const loading = ref(false)
const matrix = ref(null)       // { units, uploaded, cells, pairs, kpi, mode }
const batches = ref([])        // 与 units 对齐；元素 {detail?, balance?}|null
const units = computed(() => matrix.value?.units || [])
const activeTab = ref('matrix')   // matrix | pair

async function load() {
  loading.value = true
  try {
    const [m, b] = await Promise.all([
      api.get('/internal/matrix', { params: { year: year.value, month: month.value } }),
      api.get('/internal/batches', { params: { year: year.value, month: month.value } }),
    ])
    matrix.value = m.data
    batches.value = b.data.batches
  } catch (e) { toast.error(e?.msg || e?.error || '加载失败')
  } finally { loading.value = false }
}
watch([year, month], () => { load(); if (pairA.value && pairB.value) loadPair() })
onMounted(load)

const kpi = computed(() => matrix.value?.kpi || {})
const uploadedSet = computed(() => new Set(matrix.value?.uploaded || []))
const hasAnyData = computed(() => (matrix.value?.uploaded || []).length > 0)

// ── 矩阵着色与十字高亮 ────────────────────────────────────────────────────────
const pairDiffMap = computed(() => {
  const m = {}
  for (const p of matrix.value?.pairs || []) {
    m[`${p.a}|${p.b}`] = p; m[`${p.b}|${p.a}`] = p
  }
  return m
})
function cellPair(a, b) { return pairDiffMap.value[`${a}|${b}`] || null }
function cellCls(a, b) {
  const p = cellPair(a, b)
  if (!p) return ''
  if (!p.both_uploaded) return 'c-partial'
  return Math.abs(p.diff) < 0.005 ? 'c-ok' : 'c-diff'
}
// 差异格背景：单色（红）按差异强度做明度渐变（sequential）
const maxAbsDiff = computed(() => Math.max(
  1, ...(matrix.value?.pairs || []).filter(p => p.both_uploaded).map(p => Math.abs(p.diff))))
function cellStyle(a, b) {
  const p = cellPair(a, b)
  if (!p || !p.both_uploaded || Math.abs(p.diff) < 0.005) return null
  const t = Math.min(1, Math.abs(p.diff) / maxAbsDiff.value)
  return { background: `rgba(198, 40, 40, ${(0.06 + 0.2 * t).toFixed(3)})` }
}
const hoverRC = ref({ r: -1, c: -1 })
function setHover(r, c) { hoverRC.value = { r, c } }
function clearHover() { hoverRC.value = { r: -1, c: -1 } }

const shortName = (u) => u.replace('事业部', '').replace('集团', '')
const initialOf = (u) => shortName(u).slice(0, 1)
// 排行条：差异绝对值相对最大差异的占比
function rankBarPct(p) {
  return Math.max(3, Math.round(Math.abs(p.diff) / maxAbsDiff.value * 100))
}
// 核平进度环（r=19 → 周长 ≈ 119.4）
const ringPct = computed(() =>
  kpi.value.pairs_total ? kpi.value.pairs_ok / kpi.value.pairs_total : 0)

// ── 两两比对 ────────────────────────────────────────────────────────────────
const pairA = ref('')
const pairB = ref('')
const pairData = ref(null)
const pairLoading = ref(false)
const onlyUnmatched = ref(false)
const pairKw = ref('')

async function loadPair() {
  if (!pairA.value || !pairB.value || pairA.value === pairB.value) return
  pairLoading.value = true
  try {
    const res = await api.get('/internal/pair', {
      params: { year: year.value, month: month.value, a: pairA.value, b: pairB.value } })
    pairData.value = res.data
  } catch (e) { toast.error(e?.msg || e?.error || '加载失败')
  } finally { pairLoading.value = false }
}
function openPair(a, b) {
  pairA.value = a; pairB.value = b
  activeTab.value = 'pair'
  loadPair()
}
function swapPair() {
  const t = pairA.value; pairA.value = pairB.value; pairB.value = t
  loadPair()
}
function filterRows(rows) {
  let r = rows || []
  if (onlyUnmatched.value) r = r.filter(x => !x.match)
  const kw = pairKw.value.trim()
  if (kw) r = r.filter(x => (x.summary || '').includes(kw) || (x.voucher_no || '').includes(kw) || (x.subject_name || '').includes(kw))
  return r
}
const aShown = computed(() => filterRows(pairData.value?.a_rows))
const bShown = computed(() => filterRows(pairData.value?.b_rows))
// 区分「无明细数据」与「差异为零」：两侧都没有明细行时不显示 0.00（会被误读为核平）
const pairHasDetail = computed(() =>
  (pairData.value?.a_rows?.length || 0) + (pairData.value?.b_rows?.length || 0) > 0)
// 自动配对金额覆盖率（相对两侧明细绝对额较大的一侧）
const matchCoverage = computed(() => {
  const d = pairData.value
  if (!d || !pairHasDetail.value) return 0
  const sumAbs = rows => rows.reduce((s, r) => s + Math.abs(r.signed || 0), 0)
  const base = Math.max(sumAbs(d.a_rows), sumAbs(d.b_rows))
  return base ? Math.min(1, d.matched_amount / base) : 0
})

// ── 上传 ────────────────────────────────────────────────────────────────────
const showUpload = ref(false)
const upBu = ref('')
const upFile = ref(null)
const upDropping = ref(false)
const uploading = ref(false)
const upResult = ref(null)
function openUpload(bu) {
  upBu.value = bu || ''
  upFile.value = null; upResult.value = null
  showUpload.value = true
}
function onUpPick(e) { upFile.value = e.target.files[0] || null }
function onUpDrop(e) {
  upDropping.value = false
  const f = Array.from(e.dataTransfer?.files || [])[0]
  if (!f) return
  if (!/\.xlsx?$/i.test(f.name)) { toast.error(`不支持的文件类型：${f.name}（请拖入 .xlsx/.xls）`); return }
  upFile.value = f
}
async function doUpload() {
  if (!upFile.value) { toast.error('请选择金蝶导出的文件'); return }
  uploading.value = true
  upResult.value = null
  try {
    const fd = new FormData()
    fd.append('bu', upBu.value)
    fd.append('year', year.value)
    fd.append('month', month.value)
    fd.append('file', upFile.value)
    const res = await api.post('/internal/upload', fd)
    upResult.value = res.data
    toast.success(`已导入 ${res.data.rows} 行`)
    upFile.value = null
    load()
    if (pairData.value) loadPair()
  } catch (e) { toast.error(e?.msg || e?.error || '上传失败')
  } finally { uploading.value = false }
}
async function delBatch(b) {
  if (!b) return
  if (!(await confirmDlg(`删除「${b.business_unit}」${b.year}年${b.month}月的${b.kind === 'balance' ? '余额' : '明细'}数据（${b.row_count} 行）？删除后矩阵与比对将不含该数据。`))) return
  try {
    await api.delete(`/internal/batches/${b.id}`)
    toast.success('已删除')
    load()
    if (pairData.value) loadPair()
  } catch (e) { toast.error(e?.msg || e?.error || '删除失败') }
}

const fmt = (v) => fmtMoney(v, '0.00')
const fmtDiff = (v) => (Math.abs(v) < 0.005 ? '0.00' : fmtMoney(v))
const compact = (v) => fmtCompact(v, { dash: '0' })
</script>

<template>
  <div class="ir-view">
    <!-- ══ 指挥舱横幅：期间 · 差异总额 · 核平进度环 ═══════════════════════ -->
    <header class="hero">
      <div class="hero-main">
        <div class="hero-title">
          <div class="hero-eyebrow">INTERCOMPANY · 镜像核对</div>
          <h1>内部往来核对</h1>
          <div class="hero-mode">
            <span class="mode-pill" :class="matrix?.mode === 'balance' ? 'is-bal' : 'is-det'"
              :title="matrix?.mode === 'balance' ? '按期末余额核对（含期初遗留差异）' : '按本期发生净额核对：上传余额表可切换为期末口径'">
              {{ matrix?.mode === 'balance' ? '◉ 期末余额口径' : '◎ 本期发生口径' }}
            </span>
          </div>
        </div>
        <div class="hero-stats">
          <div class="hs">
            <div class="hs-l">内往应收</div>
            <div class="hs-v" :title="fmt(kpi.total_ar)">{{ compact(kpi.total_ar) }}</div>
          </div>
          <div class="hs">
            <div class="hs-l">内往应付</div>
            <div class="hs-v" :title="fmt(kpi.total_ap)">{{ compact(kpi.total_ap) }}</div>
          </div>
          <div class="hs hs-hero" :class="kpi.total_diff > 0.005 ? 'is-diff' : 'is-ok'">
            <div class="hs-l">镜像差异总额</div>
            <div class="hs-v hs-big" :title="fmt(kpi.total_diff)">{{ fmtDiff(kpi.total_diff) }}</div>
            <div class="hs-foot">{{ kpi.total_diff > 0.005 ? '待核差异，点矩阵红格定位' : (kpi.pairs_total ? '全部核平' : '暂无双边数据') }}</div>
          </div>
          <div class="hs hs-ring">
            <svg viewBox="0 0 44 44" class="ring" aria-hidden="true">
              <circle cx="22" cy="22" r="19" class="ring-bg" />
              <circle cx="22" cy="22" r="19" class="ring-fg"
                :stroke-dasharray="`${(ringPct * 119.4).toFixed(1)} 119.4`"
                transform="rotate(-90 22 22)" />
            </svg>
            <div class="ring-txt">
              <b>{{ kpi.pairs_ok ?? 0 }}<i>/{{ kpi.pairs_total ?? 0 }}</i></b>
              <span>核平对</span>
            </div>
          </div>
        </div>
      </div>
      <div class="hero-ctrl">
        <div class="period-pill">
          <select v-model.number="year"><option v-for="y in YEARS" :key="y" :value="y">{{ y }} 年</option></select>
          <span class="pp-sep"></span>
          <select v-model.number="month"><option v-for="m in 12" :key="m" :value="m">{{ m }} 月</option></select>
        </div>
        <button v-if="auth.canUpload" class="btn btn-primary btn-sm" @click="openUpload('')">↑ 上传金蝶数据</button>
        <span v-if="kpi.unmatched_rows" class="warn-chip" title="维度原文无法识别为集团内主体的行（按外部往来处理，不参与核对）">
          ⚠ 未识别 {{ kpi.unmatched_rows }} 行</span>
      </div>
    </header>

    <!-- ══ 主体带：七主体上传状态卡 ══════════════════════════════════════ -->
    <div class="entities">
      <button v-for="(bu, i) in units" :key="bu"
        :class="['ent', batches[i] ? 'on' : '']"
        :title="batches[i] ? bu : `${bu}：未上传，点击上传`"
        @click="auth.canUpload && openUpload(bu)">
        <span class="ent-avatar" :class="{ lit: batches[i] }">{{ initialOf(bu) }}</span>
        <span class="ent-body">
          <span class="ent-name">{{ shortName(bu) }}</span>
          <span class="ent-tags">
            <template v-if="batches[i]">
              <span v-for="k in ['balance', 'detail']" :key="k">
                <span v-if="batches[i][k]" class="ent-tag" :class="k === 'balance' ? 't-bal' : 't-det'"
                  :title="`${k === 'balance' ? '余额表' : '明细账'} ${batches[i][k].row_count} 行 · ${batches[i][k].uploaded_by || '—'} 上传`">
                  {{ k === 'balance' ? '余' : '明' }} {{ batches[i][k].row_count }}
                  <i v-if="auth.canDelete" class="ent-x" title="删除这份数据"
                    @click.stop="delBatch(batches[i][k])">✕</i>
                </span>
              </span>
            </template>
            <span v-else class="ent-tag t-none">未上传</span>
          </span>
        </span>
      </button>
    </div>

    <!-- ══ Tab ══════════════════════════════════════════════════════════ -->
    <div class="ir-tabs">
      <button :class="['ir-tab', activeTab === 'matrix' ? 'active' : '']" @click="activeTab = 'matrix'">差异矩阵</button>
      <button :class="['ir-tab', activeTab === 'pair' ? 'active' : '']" @click="activeTab = 'pair'">两两比对</button>
    </div>

    <!-- ══ 矩阵面板 ══════════════════════════════════════════════════════ -->
    <div v-if="activeTab === 'matrix'" class="card ir-body">
      <EmptyState v-if="!loading && !hasAnyData" icon="⇄"
        text="本期间尚无内往数据 —— 上传金蝶「明细分类账」或「核算维度余额表」（支持全部账簿一次性导出）" />
      <template v-else>
        <div class="mx-wrap">
          <div class="mx-scroll" @mouseleave="clearHover">
            <table class="mx-tbl">
              <thead>
                <tr>
                  <th class="mx-corner"><span>记账方</span><span class="mx-corner2">对方</span></th>
                  <th v-for="(b, bi) in units" :key="b"
                    :class="{ dim: !uploadedSet.has(b), hl: hoverRC.c === bi }">
                    <span class="mx-hd"><i class="mx-avatar">{{ initialOf(b) }}</i>{{ shortName(b) }}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(a, ai) in units" :key="a">
                  <th :class="{ dim: !uploadedSet.has(a), hl: hoverRC.r === ai }">
                    <span class="mx-hd"><i class="mx-avatar">{{ initialOf(a) }}</i>{{ shortName(a) }}</span>
                    <span v-if="!uploadedSet.has(a)" class="mx-miss">未上传</span>
                  </th>
                  <td v-for="(b, bi) in units" :key="b"
                    :class="['mx-cell', a === b ? 'diag' : cellCls(a, b),
                             { 'hl-cross': a !== b && (hoverRC.r === ai || hoverRC.c === bi) }]"
                    :style="a !== b ? cellStyle(a, b) : null"
                    :title="a === b ? '' : `${a} 账上对 ${b} 净头寸 ${fmt(matrix?.cells?.[ai]?.[bi] || 0)}（应收+ / 应付−）\n点击进入两两明细比对`"
                    @mouseenter="setHover(ai, bi)"
                    @click="a !== b && openPair(a, b)">
                    <template v-if="a !== b">
                      <span v-if="matrix?.cells?.[ai]?.[bi]" class="mx-v">{{ compact(matrix.cells[ai][bi]) }}</span>
                      <span v-else class="mx-zero">·</span>
                    </template>
                    <span v-else class="mx-diag-i">{{ initialOf(a) }}</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="mx-legend">
            <span class="lg-item"><i class="lg lg-ok"></i>✓ 核平</span>
            <span class="lg-item"><i class="lg lg-diff"></i>差异（越深差异越大）</span>
            <span class="lg-item"><i class="lg lg-partial"></i>单边数据</span>
            <span class="lg-note">格内 = 行主体账上对列主体的净头寸（应收 + / 应付 −），单位随金额自动万/亿</span>
          </div>
        </div>

        <!-- 差异对排行：条形 = 差异绝对值占最大差异比例 -->
        <div v-if="(matrix?.pairs || []).length" class="rank">
          <div class="rank-head">
            <span class="rank-title">往来对差异排行</span>
            <span class="rank-sub">按差异绝对值降序 · 点击进入明细比对</span>
          </div>
          <div class="rank-list">
            <button v-for="(p, i) in matrix.pairs" :key="p.a + p.b" class="rk" @click="openPair(p.a, p.b)">
              <span class="rk-no">{{ i + 1 }}</span>
              <span class="rk-pair"><b>{{ shortName(p.a) }}</b><i class="rk-arr">⇄</i><b>{{ shortName(p.b) }}</b></span>
              <span class="rk-bar-track">
                <span class="rk-bar" :class="!p.both_uploaded ? 'b-partial' : (Math.abs(p.diff) < 0.005 ? 'b-ok' : 'b-diff')"
                  :style="{ width: rankBarPct(p) + '%' }"></span>
              </span>
              <span class="rk-amt" :class="Math.abs(p.diff) < 0.005 ? 'ok-t' : 'diff-t'"
                :title="`A方 ${fmt(p.a_net)} ｜ B方 ${fmt(p.b_net)}`">{{ fmtDiff(p.diff) }}</span>
              <span class="rk-st">
                <span v-if="!p.both_uploaded" class="st st-partial">◐ 单边</span>
                <span v-else-if="Math.abs(p.diff) < 0.005" class="st st-ok">✓ 核平</span>
                <span v-else class="st st-diff">✕ 差异</span>
              </span>
            </button>
          </div>
        </div>
      </template>
    </div>

    <!-- ══ 两两比对（对账工作台）══════════════════════════════════════════ -->
    <div v-else class="card ir-body">
      <div class="pr-bar">
        <select v-model="pairA" class="ir-sel"><option value="" disabled>选择 A 方</option>
          <option v-for="u in units" :key="u" :value="u" :disabled="u === pairB">{{ u }}</option></select>
        <button class="pr-swap" title="交换两侧" @click="swapPair">⇄</button>
        <select v-model="pairB" class="ir-sel"><option value="" disabled>选择 B 方</option>
          <option v-for="u in units" :key="u" :value="u" :disabled="u === pairA">{{ u }}</option></select>
        <button class="btn btn-primary btn-sm" :disabled="!pairA || !pairB || pairLoading" @click="loadPair">
          {{ pairLoading ? '比对中…' : '开始比对' }}</button>
        <label class="pr-flt"><input v-model="onlyUnmatched" type="checkbox" /> 只看未配对（差异项）</label>
        <input v-model="pairKw" class="pr-kw" placeholder="搜索摘要 / 凭证号 / 科目…" />
      </div>

      <EmptyState v-if="!pairData && !pairLoading" icon="⚖"
        text="选择两个主体开始比对 —— 金额相等且方向互镜的明细自动配对标记，剩余未配对行即差异来源" />

      <template v-if="pairData">
        <!-- 恒等式流：期初差 + 本期明细差 = 期末差 -->
        <div v-if="pairData.balance" class="flow">
          <div class="flow-chip" :class="Math.abs(pairData.balance.opening_diff) < 0.005 ? 'f-ok' : 'f-diff'">
            <span class="f-l">期初差异</span>
            <span class="f-v">{{ fmtDiff(pairData.balance.opening_diff) }}</span>
          </div>
          <span class="flow-op">＋</span>
          <div class="flow-chip" :class="!pairHasDetail ? 'f-na' : (Math.abs(pairData.diff) < 0.005 ? 'f-ok' : 'f-diff')">
            <span class="f-l">本期明细差</span>
            <span class="f-v">{{ pairHasDetail ? fmtDiff(pairData.diff) : '—' }}</span>
          </div>
          <span class="flow-op">＝</span>
          <div class="flow-chip f-strong" :class="Math.abs(pairData.balance.closing_diff) < 0.005 ? 'f-ok' : 'f-diff'">
            <span class="f-l">期末差异</span>
            <span class="f-v">{{ fmtDiff(pairData.balance.closing_diff) }}</span>
          </div>
          <span class="flow-note">
            {{ shortName(pairData.a) }} 期末 {{ fmt(pairData.balance.a.closing) }} ｜
            {{ shortName(pairData.b) }} 期末 {{ fmt(pairData.balance.b.closing) }}
            <template v-if="Math.abs(pairData.balance.opening_diff) > 0.005">
              　⚠ 期初已有差异：本期明细全配平也无法核平期末，需追溯以前期间
            </template>
          </span>
        </div>

        <!-- 明细摘要 + 配对覆盖 -->
        <div class="pr-sum">
          <div class="prs">
            <div class="prs-l">{{ shortName(pairData.a) }} 方净额（本期明细）</div>
            <div class="prs-v">{{ pairHasDetail ? fmt(pairData.a_net) : '—' }}</div>
          </div>
          <div class="prs">
            <div class="prs-l">{{ shortName(pairData.b) }} 方净额（本期明细）</div>
            <div class="prs-v">{{ pairHasDetail ? fmt(pairData.b_net) : '—' }}</div>
          </div>
          <div class="prs" :class="!pairHasDetail ? '' : (Math.abs(pairData.diff) < 0.005 ? 'ok' : 'warn')">
            <div class="prs-l">镜像差异（本期明细）</div>
            <div class="prs-v">{{ pairHasDetail ? fmtDiff(pairData.diff) : '—' }}</div>
          </div>
          <div class="prs prs-match">
            <div class="prs-l">自动配对 {{ pairData.matched_pairs }} 对 · {{ fmt(pairData.matched_amount) }}</div>
            <div class="match-track" :title="`按金额覆盖 ${Math.round(matchCoverage * 100)}%`">
              <div class="match-fill" :style="{ width: Math.round(matchCoverage * 100) + '%' }"></div>
            </div>
            <div class="prs-foot">金额覆盖 {{ Math.round(matchCoverage * 100) }}%</div>
          </div>
          <div v-if="!pairData.a_uploaded || !pairData.b_uploaded" class="prs warn">
            <div class="prs-l">提示</div>
            <div class="prs-v prs-small">{{ [!pairData.a_uploaded ? pairData.a : '', !pairData.b_uploaded ? pairData.b : ''].filter(Boolean).join('、') }} 未上传本期明细账（矩阵的余额口径不受影响）</div>
          </div>
        </div>

        <!-- 双栏台账 -->
        <div class="pr-cols">
          <div v-for="side in ['a', 'b']" :key="side" class="pr-col" :class="side === 'a' ? 'col-a' : 'col-b'">
            <div class="pr-col-head">
              <span class="pr-col-avatar">{{ initialOf(side === 'a' ? pairData.a : pairData.b) }}</span>
              <b>{{ side === 'a' ? pairData.a : pairData.b }}</b>
              <span class="pr-col-vs">账上 · 对 {{ side === 'a' ? shortName(pairData.b) : shortName(pairData.a) }}</span>
              <span class="pr-cnt">{{ (side === 'a' ? aShown : bShown).length }} 行</span>
            </div>
            <div class="pr-scroll">
              <table class="pr-tbl">
                <thead><tr><th>日期</th><th>凭证</th><th>科目</th><th>摘要</th><th class="amt">借方</th><th class="amt">贷方</th><th class="ctr">配对</th></tr></thead>
                <tbody>
                  <tr v-for="r in (side === 'a' ? aShown : bShown)" :key="r.id"
                    :class="['pr-row', r.match ? 'matched' : 'unmatched']">
                    <td class="ctr nowrap">{{ r.date || '—' }}</td>
                    <td class="nowrap">{{ r.voucher_no || '—' }}</td>
                    <td class="nowrap" :title="r.subject_code">{{ r.subject_name || r.subject_code || '—' }}</td>
                    <td class="pr-summ" :title="r.summary">{{ r.summary || '—' }}</td>
                    <td class="amt">{{ r.debit ? fmt(r.debit) : '' }}</td>
                    <td class="amt">{{ r.credit ? fmt(r.credit) : '' }}</td>
                    <td class="ctr">
                      <span v-if="r.match" class="mk mk-ok" :title="`配对组 #${r.match}：两侧金额相等且方向互镜`">✓ #{{ r.match }}</span>
                      <span v-else class="mk mk-no" title="对方账上找不到金额相等、方向互镜的记录">✕ 无对应</span>
                    </td>
                  </tr>
                  <tr v-if="!(side === 'a' ? aShown : bShown).length">
                    <td colspan="7" class="pr-empty">{{ onlyUnmatched ? '🎉 无未配对差异项' : '本期无明细' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </template>
    </div>

    <!-- ══ 上传弹窗 ══════════════════════════════════════════════════════ -->
    <div v-if="showUpload" class="modal-overlay" @click.self="showUpload = false">
      <div class="modal ir-up-modal">
        <h3>上传内部往来数据</h3>
        <p class="ir-up-tip">支持两种金蝶导出（可勾选全部账簿一次性导出，系统按「账簿」列自动拆分主体）：<br/>
          ① <b>明细分类账</b>（总账→明细分类账，核算维度=组织机构）→ 两两明细比对；期间按记账日期自动拆分<br/>
          ② <b>核算维度余额表</b>（总账→核算维度余额表）→ 差异矩阵按期末余额口径（含期初遗留差异），期间取下方所选年月<br/>
          同主体同期间重复上传将整体替换。</p>
        <div class="ir-up-row">
          <select v-model="upBu" class="ir-sel">
            <option value="">记账主体：自动识别（推荐）</option>
            <option v-for="u in units" :key="u" :value="u">{{ u }}</option>
          </select>
          <span class="ir-up-period">{{ year }} 年 {{ month }} 月</span>
        </div>
        <label class="up-drop" :class="{ filled: upFile, dropping: upDropping }"
          @dragover.prevent="upDropping = true" @dragleave="upDropping = false" @drop.prevent="onUpDrop">
          <input type="file" accept=".xlsx,.xls" hidden @change="onUpPick" />
          <span v-if="upFile">{{ upFile.name }}</span>
          <span v-else>点击选择或拖入金蝶导出的文件（.xlsx）</span>
        </label>
        <div v-if="upResult" class="ir-up-res">
          <div class="ir-up-ok">✓ 已识别为「{{ upResult.kind === 'balance' ? '核算维度余额表' : '明细分类账' }}」，
            导入 {{ upResult.rows }} 行（跳过小计/空行 {{ upResult.skipped }} 行）</div>
          <div v-if="upResult.batches?.length" class="ir-up-batches">
            <span v-for="bt in upResult.batches" :key="bt.id" class="ir-up-bt">{{ bt.business_unit }} · {{ bt.year }}-{{ String(bt.month).padStart(2, '0') }} · {{ bt.row_count }} 行</span>
          </div>
          <div v-if="upResult.unmatched?.length" class="ir-up-warn">
            <b>{{ upResult.unmatched.length }} 类往来单位未能识别为内部主体</b>（按外部往来处理，不参与核对）：
            <div class="ir-up-un"><span v-for="u in upResult.unmatched" :key="u.raw">{{ u.raw }} ×{{ u.count }}</span></div>
          </div>
        </div>
        <div class="modal-actions">
          <button class="btn btn-ghost" @click="showUpload = false">关闭</button>
          <button class="btn btn-primary" :disabled="uploading" @click="doUpload">{{ uploading ? '解析导入中…' : '上传并解析' }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ir-view { display: flex; flex-direction: column; gap: 12px; }

/* ══ 指挥舱横幅 ═══════════════════════════════════════════════════════ */
.hero {
  display: flex; align-items: stretch; justify-content: space-between; gap: 18px;
  padding: 18px 22px 16px; border-radius: 16px;
  background:
    radial-gradient(560px 200px at 8% -40%, rgba(201, 99, 66, 0.10), transparent 68%),
    radial-gradient(420px 180px at 96% 130%, rgba(91, 122, 153, 0.08), transparent 70%),
    var(--card, #fff);
  border: 1px solid var(--border);
  flex-wrap: wrap;
}
.hero-main { display: flex; align-items: stretch; gap: 28px; flex-wrap: wrap; min-width: 0; }
.hero-eyebrow {
  font-size: 9.5px; font-weight: 700; letter-spacing: 0.18em;
  color: var(--primary); opacity: 0.75; margin-bottom: 3px;
}
.hero-title h1 { margin: 0; font-size: 21px; letter-spacing: 0.02em; line-height: 1.2; }
.hero-mode { margin-top: 7px; }
.mode-pill {
  display: inline-block; padding: 2.5px 11px; border-radius: 999px;
  font-size: 10.5px; font-weight: 600; letter-spacing: 0.03em;
}
.mode-pill.is-bal { background: rgba(46, 125, 50, 0.1); color: #2e7d32; }
.mode-pill.is-det { background: rgba(201, 99, 66, 0.1); color: var(--primary); }

.hero-stats { display: flex; align-items: stretch; gap: 0; }
.hs { padding: 4px 22px; display: flex; flex-direction: column; justify-content: center; }
.hs + .hs { border-left: 1px solid var(--border); }
.hs-l { font-size: 10.5px; color: var(--muted); letter-spacing: 0.06em; margin-bottom: 2px; }
.hs-v { font-size: 19px; font-weight: 700; font-variant-numeric: tabular-nums; line-height: 1.15; }
.hs-big { font-size: 25px; letter-spacing: -0.01em; }
.hs-hero.is-diff .hs-v { color: #c62828; }
.hs-hero.is-ok .hs-v { color: #2e7d32; }
.hs-foot { font-size: 10px; color: var(--muted); margin-top: 2px; }
.hs-ring { flex-direction: row; align-items: center; gap: 10px; }
.ring { width: 52px; height: 52px; }
.ring-bg { fill: none; stroke: rgba(0, 0, 0, 0.07); stroke-width: 4.5; }
.ring-fg { fill: none; stroke: #2e7d32; stroke-width: 4.5; stroke-linecap: round; transition: stroke-dasharray 0.6s cubic-bezier(0.3, 0, 0.2, 1); }
.ring-txt { display: flex; flex-direction: column; line-height: 1.2; }
.ring-txt b { font-size: 16px; font-variant-numeric: tabular-nums; }
.ring-txt b i { font-style: normal; font-size: 11.5px; color: var(--muted); font-weight: 500; }
.ring-txt span { font-size: 10px; color: var(--muted); letter-spacing: 0.05em; }

.hero-ctrl { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
/* period-pill / pp-sep 已提为全局共用样式（style.css），此处不再定义 */
.warn-chip {
  padding: 3px 10px; border-radius: 999px; font-size: 11px;
  background: rgba(245, 127, 23, 0.13); color: var(--c-warn); cursor: help;
}

/* ══ 主体带 ═══════════════════════════════════════════════════════════ */
.entities { display: flex; gap: 8px; flex-wrap: wrap; }
.ent {
  display: inline-flex; align-items: center; gap: 8px; padding: 7px 12px 7px 8px;
  border: 1px solid var(--border); border-radius: 12px; background: var(--card, #fff);
  cursor: pointer; text-align: left; font: inherit; transition: border-color .13s, transform .13s, box-shadow .13s;
}
.ent:hover { border-color: var(--primary); transform: translateY(-1px); box-shadow: 0 3px 10px rgba(0, 0, 0, 0.06); }
.ent-avatar {
  width: 28px; height: 28px; border-radius: 9px; display: grid; place-items: center;
  font-size: 12.5px; font-weight: 700; color: #b5aca4;
  background: rgba(0, 0, 0, 0.045);
}
.ent-avatar.lit { color: #fff; background: linear-gradient(135deg, #c96342, #b04f31); }
.ent-body { display: flex; flex-direction: column; gap: 2px; }
.ent-name { font-size: 12px; font-weight: 600; color: var(--text); line-height: 1.1; }
.ent.on .ent-name { color: var(--text); }
.ent:not(.on) .ent-name { color: var(--muted); }
.ent-tags { display: flex; gap: 4px; }
.ent-tag {
  display: inline-flex; align-items: center; gap: 3px;
  padding: 0.5px 7px; border-radius: 999px; font-size: 9.5px; font-weight: 600;
}
.t-bal { background: rgba(46, 125, 50, 0.1); color: #2e7d32; }
.t-det { background: rgba(91, 122, 153, 0.12); color: #44607c; }
.t-none { background: rgba(0, 0, 0, 0.04); color: #b5aca4; font-weight: 500; }
.ent-x { font-style: normal; cursor: pointer; opacity: 0.55; padding: 0 1px; }
.ent-x:hover { opacity: 1; color: #c62828; }

/* ══ Tab ═════════════════════════════════════════════════════════════ */
.ir-tabs { display: flex; gap: 4px; padding: 3px; background: rgba(0, 0, 0, 0.04); border-radius: 10px; width: fit-content; }
.ir-tab { border: 0; background: none; padding: 6px 22px; font-size: 12.5px; font-weight: 600; color: var(--muted); border-radius: 8px; cursor: pointer; transition: all .15s; }
.ir-tab.active { background: var(--card, #fff); color: var(--text); box-shadow: 0 1px 4px rgba(0, 0, 0, 0.1); }

.ir-body { padding: 16px 18px; }
.ir-sel { padding: 5px 28px 5px 9px; font-size: 12.5px; border: 1px solid var(--border); border-radius: 8px; background-color: var(--card, #fff); color: var(--text); cursor: pointer; }

/* ══ 矩阵 ═════════════════════════════════════════════════════════════ */
.mx-wrap { display: flex; flex-direction: column; gap: 8px; }
.mx-scroll { overflow-x: auto; border: 1px solid var(--border); border-radius: 12px; }
.mx-tbl { border-collapse: separate; border-spacing: 0; width: 100%; font-size: 12px; }
.mx-tbl th, .mx-tbl td { padding: 0; border-bottom: 1px solid rgba(0, 0, 0, 0.05); }
.mx-tbl thead th { background: var(--thead-bg, #f4f1ef); padding: 8px 10px; font-size: 11px; white-space: nowrap; text-align: center; transition: background .12s; }
.mx-tbl tbody th { background: var(--thead-bg, #f4f1ef); padding: 8px 12px; font-size: 11px; white-space: nowrap; text-align: left; transition: background .12s; }
.mx-tbl thead th.hl, .mx-tbl tbody th.hl { background: rgba(201, 99, 66, 0.13); }
.mx-corner { position: relative; min-width: 96px; }
.mx-corner span { position: absolute; left: 10px; bottom: 4px; font-size: 9.5px; color: var(--muted); font-weight: 500; }
.mx-corner .mx-corner2 { left: auto; right: 10px; top: 4px; bottom: auto; }
.mx-hd { display: inline-flex; align-items: center; gap: 5px; font-weight: 600; }
.mx-avatar {
  width: 17px; height: 17px; border-radius: 5px; display: inline-grid; place-items: center;
  font-style: normal; font-size: 9.5px; font-weight: 700; color: #fff;
  background: linear-gradient(135deg, #c9a08e, #b08a77);
}
.mx-tbl th.dim .mx-avatar { background: rgba(0, 0, 0, 0.12); }
.mx-tbl th.dim { color: #b5aca4; }
.mx-miss { margin-left: 5px; font-size: 9px; color: #b5aca4; font-weight: 400; }
.mx-cell {
  cursor: pointer; text-align: right; padding: 9px 11px !important;
  font-variant-numeric: tabular-nums; transition: box-shadow .1s, background .12s; position: relative;
}
.mx-cell:hover { box-shadow: inset 0 0 0 2px var(--primary); border-radius: 6px; }
.mx-cell.hl-cross { background: rgba(201, 99, 66, 0.045); }
.mx-cell.diag {
  background: repeating-linear-gradient(45deg, transparent, transparent 4px, rgba(0, 0, 0, 0.025) 4px, rgba(0, 0, 0, 0.025) 8px);
  cursor: default; text-align: center;
}
.mx-diag-i { font-size: 10px; color: rgba(0, 0, 0, 0.14); font-weight: 700; }
.mx-cell.c-ok { background: rgba(46, 125, 50, 0.10); }
.mx-cell.c-partial { background: rgba(245, 127, 23, 0.11); }
.mx-v { font-weight: 600; color: var(--text); }
.mx-zero { color: #d5cec7; }
.mx-legend { display: flex; gap: 16px; align-items: center; font-size: 11px; color: var(--muted); flex-wrap: wrap; padding: 0 2px; }
.lg-item { display: inline-flex; align-items: center; }
.lg { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 5px; }
.lg-ok { background: rgba(46, 125, 50, 0.35); }
.lg-diff { background: linear-gradient(90deg, rgba(198, 40, 40, 0.15), rgba(198, 40, 40, 0.5)); }
.lg-partial { background: rgba(245, 127, 23, 0.4); }
.lg-note { margin-left: auto; }

/* ══ 差异对排行 ═══════════════════════════════════════════════════════ */
.rank { margin-top: 20px; }
.rank-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 8px; }
.rank-title { font-size: 13px; font-weight: 700; }
.rank-sub { font-size: 11px; color: var(--muted); }
.rank-list { display: flex; flex-direction: column; gap: 3px; }
.rk {
  display: grid; grid-template-columns: 26px 172px 1fr 130px 74px;
  align-items: center; gap: 12px; padding: 7px 12px;
  border: 1px solid transparent; border-radius: 10px; background: none;
  font: inherit; text-align: left; cursor: pointer; transition: background .12s, border-color .12s;
}
.rk:hover { background: rgba(201, 99, 66, 0.05); border-color: rgba(201, 99, 66, 0.2); }
.rk-no { font-size: 11px; font-weight: 700; color: #c9c2bb; text-align: center; }
.rk-pair { font-size: 12.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.rk-arr { font-style: normal; color: var(--muted); margin: 0 5px; font-size: 11px; }
.rk-bar-track { height: 8px; border-radius: 4px; background: rgba(0, 0, 0, 0.05); overflow: hidden; }
.rk-bar { display: block; height: 100%; border-radius: 4px; transition: width .45s cubic-bezier(0.3, 0, 0.2, 1); }
.b-diff { background: rgba(198, 40, 40, 0.55); }
.b-ok { background: rgba(46, 125, 50, 0.5); }
.b-partial { background: rgba(245, 127, 23, 0.55); }
.rk-amt { text-align: right; font-size: 12.5px; font-weight: 700; font-variant-numeric: tabular-nums; white-space: nowrap; }
.ok-t { color: #2e7d32; }
.diff-t { color: #c62828; }
.rk-st { text-align: right; }
.st { display: inline-block; padding: 2px 9px; border-radius: 999px; font-size: 10.5px; white-space: nowrap; }
.st-ok { background: rgba(46, 125, 50, 0.12); color: #2e7d32; }
.st-diff { background: rgba(198, 40, 40, 0.1); color: #c62828; }
.st-partial { background: rgba(245, 127, 23, 0.14); color: var(--c-warn); }

/* ══ 两两比对 ═════════════════════════════════════════════════════════ */
.pr-bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }
.pr-swap { border: 1px solid var(--border); background: var(--card, #fff); border-radius: 8px; padding: 4px 9px; cursor: pointer; font-size: 14px; }
.pr-swap:hover { border-color: var(--primary); color: var(--primary); }
.pr-flt { display: flex; align-items: center; gap: 5px; font-size: 12px; color: var(--muted); cursor: pointer; }
.pr-kw { flex: 1; min-width: 160px; max-width: 260px; padding: 5px 10px; font-size: 12px; border: 1px solid var(--border); border-radius: 8px; }

/* 恒等式流 */
.flow {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  padding: 12px 16px; margin-bottom: 12px;
  border: 1px dashed var(--border); border-radius: 12px; background: rgba(0, 0, 0, 0.015);
}
.flow-chip { display: flex; flex-direction: column; padding: 5px 14px; border-radius: 10px; background: var(--card, #fff); border: 1px solid var(--border); }
.flow-chip.f-strong { border-width: 1.5px; }
.flow-chip.f-ok { border-color: rgba(46, 125, 50, 0.4); }
.flow-chip.f-ok .f-v { color: #2e7d32; }
.flow-chip.f-diff { border-color: rgba(198, 40, 40, 0.4); }
.flow-chip.f-diff .f-v { color: #c62828; }
.flow-chip.f-na .f-v { color: var(--muted); }
.f-l { font-size: 9.5px; color: var(--muted); letter-spacing: 0.05em; }
.f-v { font-size: 15px; font-weight: 700; font-variant-numeric: tabular-nums; }
.flow-op { font-size: 15px; color: var(--muted); font-weight: 600; }
.flow-note { font-size: 11px; color: var(--muted); margin-left: 6px; line-height: 1.5; }

/* 明细摘要卡 */
.pr-sum { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 8px; margin-bottom: 14px; }
.prs { padding: 9px 13px; border: 1px solid var(--border); border-radius: 12px; }
.prs-l { font-size: 10.5px; color: var(--muted); }
.prs-v { font-size: 15.5px; font-weight: 700; font-variant-numeric: tabular-nums; margin-top: 1px; }
.prs-small { font-size: 12px; line-height: 1.45; }
.prs-foot { font-size: 10px; color: var(--muted); margin-top: 3px; }
.prs.warn { border-color: rgba(198, 40, 40, 0.35); }
.prs.warn .prs-v { color: #c62828; }
.prs.ok { border-color: rgba(46, 125, 50, 0.35); }
.prs.ok .prs-v { color: #2e7d32; }
.match-track { height: 7px; border-radius: 4px; background: rgba(0, 0, 0, 0.06); overflow: hidden; margin-top: 7px; }
.match-fill { height: 100%; border-radius: 4px; background: linear-gradient(90deg, #7cb682, #2e7d32); transition: width .5s cubic-bezier(0.3, 0, 0.2, 1); }

/* 双栏台账 */
.pr-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; align-items: start; }
@media (max-width: 1100px) { .pr-cols { grid-template-columns: 1fr; } }
.pr-col { border: 1px solid var(--border); border-radius: 14px; overflow: hidden; }
.pr-col.col-a { box-shadow: inset 0 3px 0 rgba(201, 99, 66, 0.55); }
.pr-col.col-b { box-shadow: inset 0 3px 0 rgba(91, 122, 153, 0.55); }
.pr-col-head { display: flex; align-items: center; gap: 8px; padding: 10px 14px; font-size: 12.5px; background: var(--thead-bg, #f4f1ef); border-bottom: 1px solid var(--border); }
.pr-col-avatar {
  width: 22px; height: 22px; border-radius: 7px; display: grid; place-items: center;
  font-size: 11px; font-weight: 700; color: #fff; flex-shrink: 0;
}
.col-a .pr-col-avatar { background: linear-gradient(135deg, #c96342, #b04f31); }
.col-b .pr-col-avatar { background: linear-gradient(135deg, #5b7a99, #44607c); }
.pr-col-vs { color: var(--muted); font-size: 11.5px; }
.pr-cnt { margin-left: auto; font-size: 11px; color: var(--muted); }
.pr-scroll { max-height: 520px; overflow: auto; }
.pr-tbl { width: 100%; border-collapse: collapse; font-size: 12px; }
.pr-tbl th { position: sticky; top: 0; background: var(--card, #fff); font-size: 10.5px; color: var(--muted); text-align: left; padding: 6px 9px; border-bottom: 1px solid var(--border); z-index: 2; }
.pr-tbl td { padding: 5.5px 9px; border-bottom: 1px solid rgba(0, 0, 0, 0.045); }
.pr-tbl .amt { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.pr-tbl .ctr { text-align: center; }
.nowrap { white-space: nowrap; }
.pr-summ { max-width: 210px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pr-row.matched { background: rgba(46, 125, 50, 0.05); }
.pr-row.matched td:first-child { box-shadow: inset 3px 0 0 rgba(46, 125, 50, 0.55); }
.pr-row.unmatched td:first-child { box-shadow: inset 3px 0 0 rgba(198, 40, 40, 0.5); }
.mk { display: inline-block; padding: 1px 7px; border-radius: 999px; font-size: 10.5px; white-space: nowrap; }
.mk-ok { background: rgba(46, 125, 50, 0.13); color: #2e7d32; }
.mk-no { background: rgba(198, 40, 40, 0.1); color: #c62828; }
.pr-empty { text-align: center; color: var(--muted); padding: 24px; }

/* ══ 上传弹窗 ═════════════════════════════════════════════════════════ */
.ir-up-modal { width: min(560px, 92vw); }
.ir-up-tip { font-size: 12px; color: var(--muted); line-height: 1.6; margin: 6px 0 12px; }
.ir-up-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.ir-up-period { font-size: 12.5px; color: var(--muted); }
.up-drop {
  display: flex; align-items: center; justify-content: center; gap: 10px;
  padding: 22px 16px; border-radius: 12px; cursor: pointer; font-size: 12.5px;
  border: 1.5px dashed rgba(201, 99, 66, 0.35); background: rgba(201, 99, 66, 0.03);
  color: var(--muted); transition: all .13s;
}
.up-drop:hover, .up-drop.dropping { border-color: var(--primary); color: var(--primary); background: rgba(201, 99, 66, 0.06); }
.up-drop.filled { border-style: solid; border-color: var(--primary); color: var(--text); }
.ir-up-res { margin-top: 10px; font-size: 12px; }
.ir-up-ok { color: #2e7d32; }
.ir-up-batches { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 6px; }
.ir-up-bt { padding: 1px 8px; background: rgba(46, 125, 50, 0.1); color: #2e7d32; border-radius: 999px; font-size: 11px; }
.ir-up-warn { margin-top: 6px; color: var(--c-warn); line-height: 1.5; }
.ir-up-un { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 4px; }
.ir-up-un span { padding: 1px 8px; background: rgba(245, 127, 23, 0.12); border-radius: 999px; font-size: 11px; }

/* 窄屏 */
@media (max-width: 900px) {
  .hero { flex-direction: column; }
  .hero-stats { flex-wrap: wrap; }
  .hs { padding: 4px 14px; }
  .rk { grid-template-columns: 22px 130px 1fr 108px; }
  .rk-st { display: none; }
}
</style>
