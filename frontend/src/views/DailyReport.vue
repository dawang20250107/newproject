<template>
  <div class="page">
    <!-- Header -->
    <div class="dr-header">
      <div class="date-nav">
        <button class="nav-arrow" @click="shiftDate(-1)">&lsaquo;</button>
        <input type="date" class="date-input" v-model="currentDate" @change="onDateChange" />
        <button class="nav-arrow" @click="shiftDate(1)">&rsaquo;</button>
        <span class="date-label-today" v-if="currentDate === todayISO()" >今天</span>
      </div>
      <div class="tabs">
        <button :class="['tab', tab === 'edit' ? 'tab-on' : '']" @click="tab = 'edit'">填写日报</button>
        <button :class="['tab', tab === 'calendar' ? 'tab-on' : '']" @click="switchTab('calendar')">日历记录</button>
        <button :class="['tab', tab === 'week' ? 'tab-on' : '']" @click="switchTab('week')">周分析</button>
      </div>
    </div>

    <!-- ═══ Tab: 填写日报 ═══ -->
    <div v-if="tab === 'edit'" class="edit-panel">
      <!-- 基本信息 -->
      <div class="card">
        <div class="card-title">① 基本信息</div>
        <div class="field-row">
          <div class="field">
            <label>部门</label>
            <input v-model="form.dept" @input="markDirty" placeholder="部门" />
          </div>
          <div class="field">
            <label>岗位</label>
            <input v-model="form.role" @input="markDirty" placeholder="岗位" />
          </div>
          <div class="field">
            <label>姓名</label>
            <input v-model="form.name" @input="markDirty" placeholder="姓名" />
          </div>
        </div>
      </div>

      <!-- 任务录入 -->
      <div class="card">
        <div class="card-title">② 任务录入
          <span class="card-hint">一时段一卡片，卡片内可加多条并行任务</span>
        </div>

        <div v-for="(blk, bi) in form.blocks" :key="bi" class="block">
          <div class="block-hd">
            <span class="blk-num">{{ bi + 1 }}</span>
            <input type="time" class="time-inp" v-model="blk.start" @change="refreshDuration(bi); markDirty()" />
            <span class="arrow">→</span>
            <input type="time" class="time-inp" v-model="blk.end" @change="refreshDuration(bi); markDirty()" />
            <span v-if="blk.duration" class="dur-badge">{{ blk.duration }}</span>
            <button class="blk-del" @click="removeBlock(bi)">✕</button>
          </div>

          <div v-for="(task, ti) in blk.tasks" :key="ti" class="task">
            <div class="task-row">
              <span class="bullet">•</span>
              <textarea
                v-model="task.desc"
                class="task-desc"
                placeholder="任务描述"
                rows="1"
                @input="autoResize($event); markDirty()"
              />
              <button class="task-del" @click="removeTask(bi, ti)">×</button>
            </div>
            <div class="prog-row">
              <input type="range" min="0" max="100" v-model.number="task.progress"
                @input="markDirty"
                :style="{ '--prog-color': task.progress >= 100 ? '#4ade80' : '#d97757' }" />
              <span :class="['prog-lbl', task.progress >= 100 ? 'done' : '']">
                {{ task.progress >= 100 ? '✓ 已完成' : task.progress + '%' }}
              </span>
              <button v-if="task.progress < 100" class="done-btn" @click="task.progress = 100; markDirty()">完成</button>
            </div>
          </div>

          <button class="add-task" @click="blk.tasks.push({ desc: '', progress: 0 }); markDirty()">＋ 添加任务</button>
        </div>

        <div class="block-toolbar">
          <button class="btn-ghost" @click="addBlock">＋ 添加时段</button>
          <button class="btn-danger" @click="clearBlocks">清空全部</button>
        </div>
      </div>

      <!-- 复盘 -->
      <div class="card">
        <div class="card-title">③ 复盘 &amp; 明日计划</div>
        <div class="form-row">
          <label>行得通的是</label>
          <textarea v-model="form.works" @input="markDirty" placeholder="无" rows="2" />
        </div>
        <div class="form-row">
          <label>行不通的是</label>
          <textarea v-model="form.notWorks" @input="markDirty" placeholder="无" rows="2" />
        </div>
        <div class="form-row">
          <label>明日计划</label>
          <textarea v-model="form.plans" @input="markDirty" placeholder="每行一条..." rows="3" />
        </div>
        <div class="form-row">
          <label>结语</label>
          <input v-model="form.commit" @input="markDirty" placeholder="每天结尾的一句话" />
        </div>
      </div>

      <!-- 保存按钮 -->
      <div class="save-area">
        <div class="save-status">
          <span v-if="savedAt && !isDirty" class="status-saved">✓ 已保存 {{ savedAt }}</span>
          <span v-else-if="isDirty" class="status-dirty">有未保存的修改</span>
        </div>
        <button
          class="btn-save"
          :class="{ 'btn-save-dirty': isDirty, 'btn-save-ok': !isDirty && savedAt }"
          :disabled="isSaving || !isDirty"
          @click="saveReport"
        >
          <span v-if="isSaving" class="spinner"></span>
          {{ isSaving ? '保存中...' : isDirty ? '💾 保存日报' : '✓ 已保存' }}
        </button>
      </div>
    </div>

    <!-- ═══ Tab: 日历记录 ═══ -->
    <div v-if="tab === 'calendar'" class="calendar-panel">
      <div class="cal-nav">
        <button class="nav-arrow" @click="shiftMonth(-1)">&lsaquo;</button>
        <span class="cal-title">{{ calYear }}年{{ calMonth }}月</span>
        <button class="nav-arrow" @click="shiftMonth(1)">&rsaquo;</button>
      </div>
      <div v-if="calLoading" class="cal-loading">加载中...</div>
      <div v-else class="cal-grid">
        <div v-for="h in ['一','二','三','四','五','六','日']" :key="h" class="cal-head">{{ h }}</div>
        <div
          v-for="cell in calCells"
          :key="cell.date"
          :class="['cal-cell', {
            'other-month': !cell.inMonth,
            'has-report': cell.hasReport,
            'is-today': cell.isToday,
            'is-selected': cell.date === currentDate,
          }]"
          @click="cell.inMonth && goToDate(cell.date)"
        >
          <span class="cal-day">{{ cell.day }}</span>
          <span v-if="cell.hasReport" class="cal-dot"></span>
        </div>
      </div>
      <div class="cal-legend">
        <span class="dot-legend"></span> 已填写日报
      </div>
    </div>

    <!-- ═══ Tab: 周分析 ═══ -->
    <div v-if="tab === 'week'" class="week-panel">
      <div class="week-nav">
        <button class="nav-arrow" @click="shiftWeek(-1)">&lsaquo; 上周</button>
        <span class="week-range">{{ weekAnchor ? weekRangeLabel : '...' }}</span>
        <button class="nav-arrow" @click="shiftWeek(1)">下周 &rsaquo;</button>
      </div>

      <div v-if="weekLoading" class="cal-loading">加载中...</div>
      <template v-else-if="weekData">
        <div class="week-stats">
          <div class="stat-card">
            <span class="stat-num">{{ weekData.total_hours }}</span>
            <span class="stat-lbl">工时（h）</span>
          </div>
          <div class="stat-card">
            <span class="stat-num">{{ weekData.completed_count }}</span>
            <span class="stat-lbl">已完成任务</span>
          </div>
          <div class="stat-card">
            <span class="stat-num">{{ weekData.days.filter(d => d.has_report).length }}</span>
            <span class="stat-lbl">填报天数</span>
          </div>
        </div>

        <div v-for="day in weekData.days" :key="day.date" class="week-day">
          <div class="week-day-hd">
            <span class="wd-label">周{{ day.weekday }}</span>
            <span class="wd-date">{{ day.date }}</span>
            <span v-if="day.has_report" class="wd-hours">{{ day.hours }}h</span>
            <span v-else class="wd-empty">未填报</span>
          </div>
          <div v-if="day.completed_tasks.length" class="task-list">
            <div v-for="(t, i) in day.completed_tasks" :key="i" class="task-done">✓ {{ t }}</div>
          </div>
          <div v-else-if="day.has_report" class="no-done">无已完成任务</div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { report } from '@/api/index.js'

// ─── helpers ───────────────────────────────────────────────
function todayISO() {
  const d = new Date()
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}
function pad(n) { return String(n).padStart(2, '0') }
function computeDuration(s, e) {
  if (!s || !e) return ''
  const [sh, sm] = s.split(':').map(Number)
  const [eh, em] = e.split(':').map(Number)
  const mins = (eh * 60 + em) - (sh * 60 + sm)
  if (mins <= 0) return ''
  const h = Math.floor(mins / 60), m = mins % 60
  if (h === 0) return m + 'min'
  if (m === 0) return h + 'h'
  return `${h}h${m}min`
}
function isoDate(d) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}
function fmtTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// ─── state ─────────────────────────────────────────────────
const tab = ref('edit')
const currentDate = ref(todayISO())

const form = reactive({
  dept: '', role: '', name: '',
  blocks: [],
  works: '', notWorks: '', plans: '',
  commit: '--我承诺明天创造更高效的结果！',
})

const isDirty = ref(false)
const isSaving = ref(false)
const savedAt = ref(null)

// Calendar
const calYear = ref(new Date().getFullYear())
const calMonth = ref(new Date().getMonth() + 1)
const reportDates = ref([])
const calLoading = ref(false)

// Week
const weekAnchor = ref(todayISO())
const weekData = ref(null)
const weekLoading = ref(false)

// ─── computed ──────────────────────────────────────────────
const calCells = computed(() => {
  const year = calYear.value
  const month = calMonth.value
  const firstDay = new Date(year, month - 1, 1)
  const daysInMonth = new Date(year, month, 0).getDate()
  const today = todayISO()

  let startDow = firstDay.getDay()
  startDow = (startDow + 6) % 7  // Monday = 0

  const cells = []
  // Prev month padding
  for (let i = 0; i < startDow; i++) {
    const d = new Date(year, month - 1, i - startDow + 1)
    cells.push({ date: isoDate(d), day: d.getDate(), inMonth: false, hasReport: false, isToday: false })
  }
  // Current month
  for (let d = 1; d <= daysInMonth; d++) {
    const date = `${year}-${pad(month)}-${pad(d)}`
    cells.push({
      date, day: d, inMonth: true,
      hasReport: reportDates.value.includes(date),
      isToday: date === today,
    })
  }
  // Next month padding
  const rem = (7 - (cells.length % 7)) % 7
  for (let i = 1; i <= rem; i++) {
    const d = new Date(year, month, i)
    cells.push({ date: isoDate(d), day: i, inMonth: false, hasReport: false, isToday: false })
  }
  return cells
})

const weekRangeLabel = computed(() => {
  if (!weekData.value) return ''
  return `${weekData.value.week_start} — ${weekData.value.week_end}`
})

// ─── load report ──────────────────────────────────────────
async function loadReport() {
  isDirty.value = false
  savedAt.value = null
  try {
    const data = await report.get(currentDate.value)
    form.dept = data.dept || ''
    form.role = data.role || ''
    form.name = data.name || ''
    form.blocks = (data.blocks || []).map(b => ({
      ...b,
      duration: computeDuration(b.start, b.end),
    }))
    form.works = data.works || ''
    form.notWorks = data.not_works || ''
    form.plans = data.plans || ''
    form.commit = data.commit || '--我承诺明天创造更高效的结果！'
    if (data.updated_at) savedAt.value = fmtTime(data.updated_at)
  } catch (e) {
    console.error('load report failed', e)
  }
}

// ─── save report ──────────────────────────────────────────
async function saveReport() {
  if (!isDirty.value || isSaving.value) return
  isSaving.value = true
  try {
    const res = await report.save(currentDate.value, {
      dept: form.dept, role: form.role, name: form.name,
      blocks: form.blocks,
      works: form.works, not_works: form.notWorks,
      plans: form.plans, commit: form.commit,
    })
    isDirty.value = false
    savedAt.value = fmtTime(res.updated_at)
    // refresh calendar dot if on same month
    if (!reportDates.value.includes(currentDate.value)) {
      const [y, m] = currentDate.value.split('-').map(Number)
      if (y === calYear.value && m === calMonth.value) {
        reportDates.value = [...reportDates.value, currentDate.value]
      }
    }
  } catch (e) {
    alert('保存失败: ' + (e.response?.data?.error || e.message))
  } finally {
    isSaving.value = false
  }
}

function markDirty() { isDirty.value = true }

// ─── blocks / tasks ───────────────────────────────────────
function addBlock() {
  form.blocks.push({ start: '', end: '', duration: '', tasks: [{ desc: '', progress: 0 }] })
  isDirty.value = true
}
function removeBlock(bi) {
  form.blocks.splice(bi, 1)
  isDirty.value = true
}
function removeTask(bi, ti) {
  const tasks = form.blocks[bi].tasks
  tasks.splice(ti, 1)
  if (tasks.length === 0) tasks.push({ desc: '', progress: 0 })
  isDirty.value = true
}
function refreshDuration(bi) {
  const b = form.blocks[bi]
  b.duration = computeDuration(b.start, b.end)
}
function clearBlocks() {
  if (!confirm('清空所有时段和任务？')) return
  form.blocks = [{ start: '', end: '', duration: '', tasks: [{ desc: '', progress: 0 }] }]
  isDirty.value = true
}
function autoResize(e) {
  e.target.style.height = 'auto'
  e.target.style.height = e.target.scrollHeight + 'px'
}

// ─── date navigation ──────────────────────────────────────
function shiftDate(delta) {
  const d = new Date(currentDate.value)
  d.setDate(d.getDate() + delta)
  currentDate.value = isoDate(d)
  loadReport()
}
function onDateChange() { loadReport() }

// ─── calendar ─────────────────────────────────────────────
async function switchTab(t) {
  tab.value = t
  if (t === 'calendar') await loadCalendar()
  else if (t === 'week') await loadWeek()
}

async function loadCalendar() {
  calLoading.value = true
  try {
    const data = await report.list(calYear.value, calMonth.value)
    reportDates.value = data.dates || []
  } catch (e) {
    console.error(e)
  } finally {
    calLoading.value = false
  }
}

async function shiftMonth(delta) {
  let m = calMonth.value + delta
  let y = calYear.value
  if (m > 12) { m = 1; y++ }
  if (m < 1) { m = 12; y-- }
  calMonth.value = m
  calYear.value = y
  await loadCalendar()
}

function goToDate(date) {
  currentDate.value = date
  tab.value = 'edit'
  loadReport()
}

// ─── week ─────────────────────────────────────────────────
async function loadWeek() {
  weekLoading.value = true
  try {
    weekData.value = await report.week(weekAnchor.value)
  } catch (e) {
    console.error(e)
  } finally {
    weekLoading.value = false
  }
}

function shiftWeek(delta) {
  const d = new Date(weekAnchor.value)
  d.setDate(d.getDate() + delta * 7)
  weekAnchor.value = isoDate(d)
  loadWeek()
}

// ─── init ─────────────────────────────────────────────────
onMounted(loadReport)
</script>

<style scoped>
.page { padding-bottom: 60px; }

/* Header */
.dr-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  padding: 10px 0 20px;
}
.date-nav {
  display: flex;
  align-items: center;
  gap: 8px;
}
.date-input {
  padding: 7px 12px;
  background: var(--bg-card, #1e293b);
  border: 1px solid rgba(212,175,55,0.2);
  border-radius: 8px;
  color: var(--text-primary, #e2e8f0);
  font-size: 14px;
}
.date-label-today {
  font-size: 12px;
  background: rgba(212,175,55,0.15);
  color: #d4af37;
  padding: 3px 10px;
  border-radius: 20px;
  font-weight: 600;
}
.nav-arrow {
  padding: 6px 14px;
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 8px;
  color: var(--text-secondary, #94a3b8);
  cursor: pointer;
  font-size: 16px;
  transition: all 0.15s;
}
.nav-arrow:hover { background: rgba(255,255,255,0.1); color: #e2e8f0; }

/* Tabs */
.tabs { display: flex; gap: 4px; }
.tab {
  padding: 7px 18px;
  border-radius: 8px;
  border: 1px solid transparent;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  color: rgba(148,163,184,0.8);
  background: transparent;
  transition: all 0.15s;
}
.tab:hover { color: #e2e8f0; background: rgba(255,255,255,0.05); }
.tab-on {
  background: rgba(212,175,55,0.15);
  border-color: rgba(212,175,55,0.3);
  color: #d4af37;
}

/* Cards */
.card {
  background: var(--bg-card, rgba(30,41,59,0.8));
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 14px;
  padding: 24px;
  margin-bottom: 16px;
}
.card-title {
  font-size: 14px;
  font-weight: 600;
  color: #e2e8f0;
  margin-bottom: 18px;
}
.card-hint { font-size: 12px; color: rgba(148,163,184,0.6); font-weight: normal; margin-left: 8px; }

/* Basic info */
.field-row { display: flex; gap: 16px; flex-wrap: wrap; }
.field { flex: 1; min-width: 120px; }
.field label, .form-row label {
  display: block;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: rgba(148,163,184,0.6);
  margin-bottom: 6px;
}
.field input, .form-row input, .form-row textarea {
  width: 100%;
  box-sizing: border-box;
  padding: 9px 13px;
  background: rgba(15,23,42,0.5);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 8px;
  color: #e2e8f0;
  font-size: 13px;
  resize: vertical;
  outline: none;
  font-family: inherit;
  transition: border-color 0.15s;
}
.field input:focus, .form-row input:focus, .form-row textarea:focus {
  border-color: rgba(212,175,55,0.35);
}

/* Blocks */
.block {
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 10px;
  margin-bottom: 14px;
  overflow: hidden;
  background: rgba(15,23,42,0.3);
}
.block-hd {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 14px;
  background: rgba(255,255,255,0.03);
  border-bottom: 1px solid rgba(255,255,255,0.04);
  flex-wrap: wrap;
}
.blk-num {
  width: 26px; height: 26px;
  border-radius: 50%;
  background: linear-gradient(135deg, #d97757, #b85537);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.time-inp {
  padding: 6px 10px;
  background: rgba(15,23,42,0.6);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 7px;
  color: #e2e8f0;
  font-size: 13px;
  width: 105px;
}
.arrow { color: rgba(148,163,184,0.4); font-size: 14px; }
.dur-badge {
  font-size: 12px;
  color: #d97757;
  background: rgba(217,119,87,0.15);
  border-radius: 20px;
  padding: 3px 12px;
}
.blk-del {
  margin-left: auto;
  background: transparent;
  border: none;
  color: rgba(148,163,184,0.4);
  font-size: 16px;
  cursor: pointer;
  padding: 2px 6px;
}
.blk-del:hover { color: #ef4444; }

/* Tasks */
.task {
  padding: 12px 14px 8px;
  border-bottom: 1px solid rgba(255,255,255,0.04);
}
.task-row { display: flex; align-items: flex-start; gap: 8px; }
.bullet { color: #d97757; font-size: 18px; line-height: 1.5; flex-shrink: 0; margin-top: 3px; }
.task-desc {
  flex: 1;
  background: transparent;
  border: none;
  border-bottom: 1px solid rgba(255,255,255,0.06);
  color: #e2e8f0;
  font-size: 13px;
  padding: 4px 0;
  resize: none;
  font-family: inherit;
  line-height: 1.6;
  overflow: hidden;
  min-height: 26px;
  outline: none;
}
.task-desc:focus { border-bottom-color: rgba(212,175,55,0.3); }
.task-del {
  background: none; border: none;
  color: rgba(148,163,184,0.3); font-size: 18px; cursor: pointer;
  padding: 2px 4px; flex-shrink: 0;
}
.task-del:hover { color: #ef4444; }

.prog-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-left: 26px;
  margin-top: 4px;
}
.prog-row input[type=range] {
  flex: 1;
  accent-color: var(--prog-color, #d97757);
  height: 4px;
}
.prog-lbl { font-size: 12px; color: rgba(148,163,184,0.6); white-space: nowrap; }
.prog-lbl.done { color: #4ade80; font-weight: 600; }
.done-btn {
  font-size: 11px;
  padding: 3px 10px;
  background: rgba(74,222,128,0.1);
  border: 1px solid rgba(74,222,128,0.25);
  border-radius: 6px;
  color: #4ade80;
  cursor: pointer;
}

.add-task {
  display: block;
  width: calc(100% - 28px);
  margin: 8px 14px 12px;
  padding: 9px;
  background: transparent;
  border: 1px dashed rgba(217,119,87,0.3);
  border-radius: 8px;
  color: #d97757;
  font-size: 13px;
  cursor: pointer;
}
.add-task:hover { background: rgba(217,119,87,0.06); }

.block-toolbar {
  display: flex;
  gap: 10px;
  margin-top: 4px;
}
.btn-ghost {
  flex: 1;
  padding: 10px;
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 8px;
  color: #e2e8f0;
  font-size: 13px;
  cursor: pointer;
}
.btn-ghost:hover { background: rgba(255,255,255,0.08); }
.btn-danger {
  padding: 10px 18px;
  background: transparent;
  border: 1px solid rgba(239,68,68,0.3);
  border-radius: 8px;
  color: #f87171;
  font-size: 13px;
  cursor: pointer;
}
.btn-danger:hover { background: rgba(239,68,68,0.08); }

/* Review form */
.form-row { margin-bottom: 16px; }

/* Save area */
.save-area {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 8px 0;
}
.save-status { font-size: 13px; }
.status-saved { color: #4ade80; }
.status-dirty { color: #fbbf24; }
.btn-save {
  padding: 11px 32px;
  border-radius: 10px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  border: none;
  display: flex;
  align-items: center;
  gap: 8px;
  transition: all 0.2s;
}
.btn-save-dirty {
  background: linear-gradient(135deg, #d4af37, #a16207);
  color: #0f172a;
}
.btn-save-dirty:hover { opacity: 0.9; transform: translateY(-1px); }
.btn-save-ok {
  background: rgba(74,222,128,0.1);
  color: #4ade80;
  border: 1px solid rgba(74,222,128,0.25) !important;
}
.btn-save:disabled { opacity: 0.5; cursor: default; transform: none; }

/* Spinner */
.spinner {
  width: 14px; height: 14px;
  border: 2px solid rgba(0,0,0,0.3);
  border-top-color: currentColor;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* Calendar */
.calendar-panel, .week-panel { padding: 0 0 40px; }
.cal-nav, .week-nav {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 20px;
  margin-bottom: 20px;
}
.cal-title, .week-range {
  font-size: 16px;
  font-weight: 600;
  color: #e2e8f0;
  min-width: 200px;
  text-align: center;
}
.cal-loading { text-align: center; color: rgba(148,163,184,0.5); padding: 40px; }

.cal-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 4px;
  background: var(--bg-card, rgba(30,41,59,0.8));
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 14px;
  padding: 16px;
}
.cal-head {
  text-align: center;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  color: rgba(148,163,184,0.5);
  padding: 4px 0 10px;
}
.cal-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 8px 4px;
  border-radius: 8px;
  cursor: pointer;
  min-height: 48px;
  transition: background 0.15s;
  position: relative;
}
.cal-cell:hover:not(.other-month) { background: rgba(255,255,255,0.06); }
.cal-cell.other-month { opacity: 0.25; cursor: default; }
.cal-cell.is-today .cal-day { color: #d4af37; font-weight: 700; }
.cal-cell.is-selected { background: rgba(212,175,55,0.12); }
.cal-day { font-size: 14px; color: #e2e8f0; }
.cal-dot {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: #d4af37;
  margin-top: 4px;
}
.cal-legend {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 12px;
  font-size: 12px;
  color: rgba(148,163,184,0.5);
}
.dot-legend {
  display: inline-block;
  width: 6px; height: 6px;
  border-radius: 50%;
  background: #d4af37;
}

/* Week panel */
.week-stats {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
}
.stat-card {
  flex: 1;
  background: var(--bg-card, rgba(30,41,59,0.8));
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 12px;
  padding: 20px;
  text-align: center;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.stat-num {
  font-size: 32px;
  font-weight: 700;
  background: linear-gradient(135deg, #fff3b0, #d4af37);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
.stat-lbl { font-size: 12px; color: rgba(148,163,184,0.6); }

.week-day {
  background: var(--bg-card, rgba(30,41,59,0.8));
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 12px;
  padding: 16px 20px;
  margin-bottom: 10px;
}
.week-day-hd {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}
.wd-label {
  font-size: 13px;
  font-weight: 700;
  color: #d4af37;
  min-width: 30px;
}
.wd-date { font-size: 13px; color: rgba(148,163,184,0.6); flex: 1; }
.wd-hours {
  font-size: 12px;
  background: rgba(212,175,55,0.12);
  color: #d4af37;
  padding: 2px 10px;
  border-radius: 20px;
}
.wd-empty { font-size: 12px; color: rgba(148,163,184,0.3); }
.task-list { display: flex; flex-direction: column; gap: 6px; }
.task-done { font-size: 13px; color: #4ade80; padding-left: 4px; }
.no-done { font-size: 13px; color: rgba(148,163,184,0.3); padding-left: 4px; }

@media (max-width: 640px) {
  .dr-header { flex-direction: column; align-items: flex-start; }
  .week-stats { flex-wrap: wrap; }
  .stat-card { min-width: calc(50% - 6px); }
}
</style>
