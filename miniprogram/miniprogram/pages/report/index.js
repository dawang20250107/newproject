const { request } = require('../../utils/request')

function pad(n) { return n < 10 ? '0' + n : '' + n }
function fmtDate(d) { return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) }
function todayStr() { return fmtDate(new Date()) }

Page({
  data: {
    tab: 'edit',
    date: todayStr(),
    blocks: [],
    works: '',
    not_works: '',
    plans: '',
    commit_text: '',
    isDirty: false,
    isSaving: false,
    updatedAt: null,
    savedFlash: false,

    // 日历
    calYear: new Date().getFullYear(),
    calMonth: new Date().getMonth() + 1,
    calCells: [],
    calDates: [],

    // 周分析
    weekData: null,

    // AI 分析
    showModal: false,
    analysisLoading: false,
    analysisText: '',
    analysisType: 'week',
    analysisRange: '',
    copied: false,

    // 汇报生成（部门群版 / 日志群版）
    showReport: false,
    deptText: '',
    logText: '',
    deptCopied: false,
    logCopied: false,
  },

  onShow() {
    if (this.data.tab === 'edit') this._loadReport(this.data.date)
    else if (this.data.tab === 'calendar') this._loadCalendar()
    else if (this.data.tab === 'week') this._loadWeek()
  },

  onHide() { this._flushSave() },
  onUnload() { this._flushSave() },

  switchTab(e) {
    const tab = e.currentTarget.dataset.tab
    this._flushSave()
    this.setData({ tab })
    if (tab === 'edit') this._loadReport(this.data.date)
    else if (tab === 'calendar') this._loadCalendar()
    else if (tab === 'week') this._loadWeek()
  },

  // ─── 填写 ─────────────────────────────

  async _loadReport(date) {
    try {
      const r = await request('/api/reports/' + date)
      const blocks = r.blocks || []
      this.setData({
        date: r.date,
        blocks,
        works: r.works || '',
        not_works: r.not_works || '',
        plans: r.plans || '',
        commit_text: r.commit_text || '——我承诺明天创造更高效的结果！',
        isDirty: false,
        updatedAt: r.updated_at,
      })
    } catch (e) {
      wx.showToast({ title: '加载失败', icon: 'none' })
    }
  },

  // ─── 自动保存 ─────────────────────────────

  _scheduleSave() {
    if (this._saveTimer) clearTimeout(this._saveTimer)
    this._saveTimer = setTimeout(() => this._autoSave(), 1000)
  },

  async _autoSave() {
    if (!this.data.isDirty) return
    if (this.data.isSaving) { this._scheduleSave(); return }
    this.setData({ isSaving: true, isDirty: false })
    try {
      const res = await request('/api/reports/' + this.data.date, {
        method: 'PUT',
        data: {
          blocks: this.data.blocks,
          works: this.data.works,
          not_works: this.data.not_works,
          plans: this.data.plans,
          commit_text: this.data.commit_text,
        },
      })
      this.setData({ isSaving: false, updatedAt: res.updated_at, savedFlash: true })
      if (this._flashTimer) clearTimeout(this._flashTimer)
      this._flashTimer = setTimeout(() => this.setData({ savedFlash: false }), 1500)
    } catch (e) {
      this.setData({ isSaving: false, isDirty: true })
      wx.showToast({ title: '自动保存失败', icon: 'none' })
    }
  },

  _flushSave() {
    if (this._saveTimer) { clearTimeout(this._saveTimer); this._saveTimer = null }
    if (this.data.isDirty) this._autoSave()
  },

  pickDate(e) {
    const date = e.detail.value
    this._flushSave()
    this.setData({ date }, () => this._loadReport(date))
  },

  addBlock() {
    const blocks = this.data.blocks.concat([{ start: '09:00', end: '12:00', tasks: [] }])
    this.setData({ blocks, isDirty: true })
    this._scheduleSave()
  },

  removeBlock(e) {
    const i = e.currentTarget.dataset.i
    const blocks = this.data.blocks.slice()
    blocks.splice(i, 1)
    this.setData({ blocks, isDirty: true })
    this._scheduleSave()
  },

  onTimeChange(e) {
    const { i, field } = e.currentTarget.dataset
    const blocks = this.data.blocks.slice()
    blocks[i] = Object.assign({}, blocks[i], { [field]: e.detail.value })
    this.setData({ blocks, isDirty: true })
    this._scheduleSave()
  },

  addTask(e) {
    const i = e.currentTarget.dataset.i
    const blocks = this.data.blocks.slice()
    blocks[i] = Object.assign({}, blocks[i], {
      tasks: (blocks[i].tasks || []).concat([{ desc: '', progress: 0 }])
    })
    this.setData({ blocks, isDirty: true })
    this._scheduleSave()
  },

  removeTask(e) {
    const { i, j } = e.currentTarget.dataset
    const blocks = this.data.blocks.slice()
    const tasks = blocks[i].tasks.slice()
    tasks.splice(j, 1)
    blocks[i] = Object.assign({}, blocks[i], { tasks })
    this.setData({ blocks, isDirty: true })
    this._scheduleSave()
  },

  onTaskInput(e) {
    const { i, j } = e.currentTarget.dataset
    const blocks = this.data.blocks.slice()
    const tasks = blocks[i].tasks.slice()
    tasks[j] = Object.assign({}, tasks[j], { desc: e.detail.value })
    blocks[i] = Object.assign({}, blocks[i], { tasks })
    this.setData({ blocks, isDirty: true })
    this._scheduleSave()
  },

  onProgressChange(e) {
    const { i, j } = e.currentTarget.dataset
    const blocks = this.data.blocks.slice()
    const tasks = blocks[i].tasks.slice()
    tasks[j] = Object.assign({}, tasks[j], { progress: e.detail.value })
    blocks[i] = Object.assign({}, blocks[i], { tasks })
    this.setData({ blocks, isDirty: true })
    this._scheduleSave()
  },

  // 单任务完成切换（点圆圈）
  onTaskDone(e) {
    const { i, j } = e.currentTarget.dataset
    const blocks = this.data.blocks.slice()
    const tasks = blocks[i].tasks.slice()
    const current = tasks[j].progress || 0
    const next = current >= 100 ? 0 : 100
    tasks[j] = Object.assign({}, tasks[j], { progress: next })
    blocks[i] = Object.assign({}, blocks[i], { tasks })
    this.setData({ blocks, isDirty: true })
    this._scheduleSave()
    if (next === 100) {
      wx.vibrateShort({ type: 'medium' })
    }
  },

  // 整块一键完成
  blockAllDone(e) {
    const i = e.currentTarget.dataset.i
    const blocks = this.data.blocks.slice()
    const tasks = (blocks[i].tasks || []).map(t => Object.assign({}, t, { progress: 100 }))
    blocks[i] = Object.assign({}, blocks[i], { tasks })
    this.setData({ blocks, isDirty: true })
    this._scheduleSave()
    wx.vibrateShort({ type: 'medium' })
  },

  onTextInput(e) {
    const field = e.currentTarget.dataset.field
    this.setData({ [field]: e.detail.value, isDirty: true })
    this._scheduleSave()
  },

  // ─── 日历 ─────────────────────────────

  async _loadCalendar() {
    const { calYear, calMonth } = this.data
    try {
      const r = await request('/api/reports/dates?year=' + calYear + '&month=' + calMonth)
      this.setData({ calDates: r.dates || [] }, () => this._buildCells())
    } catch (e) {
      wx.showToast({ title: '加载日历失败', icon: 'none' })
    }
  },

  _buildCells() {
    const { calYear, calMonth, calDates } = this.data
    const reportSet = new Set(calDates)
    const today = todayStr()
    const first = new Date(calYear, calMonth - 1, 1)
    const last = new Date(calYear, calMonth, 0)
    const offset = (first.getDay() + 6) % 7
    const cells = []
    for (let i = 0; i < offset; i++) cells.push({ empty: true })
    for (let day = 1; day <= last.getDate(); day++) {
      const dateStr = calYear + '-' + pad(calMonth) + '-' + pad(day)
      cells.push({
        day,
        dateStr,
        hasReport: reportSet.has(dateStr),
        isToday: dateStr === today,
      })
    }
    this.setData({ calCells: cells })
  },

  prevMonth() {
    let { calYear, calMonth } = this.data
    if (--calMonth < 1) { calMonth = 12; calYear -= 1 }
    this.setData({ calYear, calMonth }, () => this._loadCalendar())
  },

  nextMonth() {
    let { calYear, calMonth } = this.data
    if (++calMonth > 12) { calMonth = 1; calYear += 1 }
    this.setData({ calYear, calMonth }, () => this._loadCalendar())
  },

  pickCell(e) {
    const dateStr = e.currentTarget.dataset.date
    if (!dateStr) return
    this._flushSave()
    this.setData({ date: dateStr, tab: 'edit' }, () => this._loadReport(dateStr))
  },

  // ─── 周分析 ─────────────────────────────

  async _loadWeek(date) {
    try {
      const d = date || this.data.date
      const r = await request('/api/reports/week?date=' + d)
      this.setData({ weekData: r })
    } catch (e) {
      wx.showToast({ title: '加载失败', icon: 'none' })
    }
  },

  weekDayTap(e) {
    const dateStr = e.currentTarget.dataset.date
    this._flushSave()
    this.setData({ date: dateStr, tab: 'edit' }, () => this._loadReport(dateStr))
  },

  // ─── AI 分析 ─────────────────────────────

  async onAnalysis(e) {
    if (this.data.analysisLoading) return
    const type = e.currentTarget.dataset.type || 'week'
    const date = this.data.weekData
      ? (type === 'week' ? this.data.weekData.week_start : this.data.date)
      : this.data.date

    this.setData({
      showModal: true,
      analysisLoading: true,
      analysisText: '',
      analysisType: type,
      analysisRange: '',
      copied: false,
    })

    try {
      const res = await request('/api/analysis', {
        method: 'POST',
        data: { type, date },
      })
      this.setData({
        analysisLoading: false,
        analysisText: res.analysis || '',
        analysisRange: res.range || '',
      })
    } catch (e) {
      this.setData({ analysisLoading: false })
      const msg = (e && e.error) ? e.error : 'AI 分析失败，请稍后重试'
      this.setData({ analysisText: msg })
    }
  },

  closeModal() {
    if (this.data.analysisLoading) return
    this.setData({ showModal: false, analysisText: '', copied: false })
  },

  // ─── 汇报生成（部门群版 / 日志群版）──────────

  _fmtReportDate(iso) {
    if (!iso) return ''
    const [, m, d] = iso.split('-').map(Number)
    return m + '月' + d + '日'
  },

  _fmtSlot(start, end) {
    const strip = (t) => { const [h, m] = t.split(':'); return parseInt(h, 10) + ':' + m }
    return strip(start) + '-' + strip(end)
  },

  _computeDuration(start, end) {
    if (!start || !end) return ''
    const [sh, sm] = start.split(':').map(Number)
    const [eh, em] = end.split(':').map(Number)
    const mins = (eh * 60 + em) - (sh * 60 + sm)
    if (mins <= 0) return ''
    const h = Math.floor(mins / 60), m = mins % 60
    if (h === 0) return m + 'min'
    if (m === 0) return h + 'h'
    return h + 'h' + m + 'min'
  },

  _statusOf(p) {
    p = Math.max(0, Math.min(100, Number(p) || 0))
    return p >= 100 ? '已完成' : ('未完成 ' + p + '%')
  },

  _buildReportTexts(prof) {
    const name = prof.name || prof.display_name || ''
    const dept = prof.dept || ''
    const role = prof.role || ''
    const date = this._fmtReportDate(this.data.date)
    const blocks = (this.data.blocks || []).filter(
      b => b.start && b.end && (b.tasks || []).some(t => t.desc)
    )

    // 部门群版：带用时，无复盘
    const deptLines = [name + '   ' + date + '：']
    blocks.forEach((b, idx) => {
      const slot = this._fmtSlot(b.start, b.end)
      const dur = this._computeDuration(b.start, b.end)
      deptLines.push(dur ? (idx + 1) + '、' + slot + '（用时' + dur + '）' : (idx + 1) + '、' + slot)
      b.tasks.filter(t => t.desc).forEach(t => {
        deptLines.push('    •' + t.desc + '（' + this._statusOf(t.progress) + '）')
      })
    })

    // 日志群版：不带用时，含复盘
    const logLines = [dept + '   ' + role + '  ' + name + '    ' + date + '：']
    blocks.forEach((b, idx) => {
      logLines.push((idx + 1) + '、' + this._fmtSlot(b.start, b.end))
      b.tasks.filter(t => t.desc).forEach(t => {
        logLines.push('    •' + t.desc + '（' + this._statusOf(t.progress) + '）')
      })
    })
    logLines.push('')
    logLines.push('行得通的是：' + (this.data.works || '无'))
    logLines.push('行不通的是：' + (this.data.not_works || '无'))
    logLines.push('明日计划：')
    const plans = (this.data.plans || '').split('\n').map(s => s.trim()).filter(Boolean)
    if (plans.length === 0) logLines.push('1、？')
    else plans.forEach((p, i) => logLines.push((i + 1) + '、' + p.replace(/^\s*\d+[、.)]\s*/, '')))
    if (this.data.commit_text) logLines.push(this.data.commit_text)

    return { deptText: deptLines.join('\n'), logText: logLines.join('\n') }
  },

  async onGenReport() {
    let prof = (getApp().globalData.profile) || {}
    try {
      const r = await request('/api/profile')
      if (r && r.profile) prof = r.profile
    } catch (e) {}
    const texts = this._buildReportTexts(prof)
    this.setData({
      showReport: true,
      deptCopied: false,
      logCopied: false,
      deptText: texts.deptText,
      logText: texts.logText,
    })
  },

  closeReport() {
    this.setData({ showReport: false })
  },

  noop() {},

  copyDept() {
    const text = this.data.deptText
    if (!text) return
    wx.setClipboardData({
      data: text,
      success: () => {
        this.setData({ deptCopied: true })
        wx.vibrateShort({ type: 'light' })
        setTimeout(() => this.setData({ deptCopied: false }), 2500)
      },
    })
  },

  copyLog() {
    const text = this.data.logText
    if (!text) return
    wx.setClipboardData({
      data: text,
      success: () => {
        this.setData({ logCopied: true })
        wx.vibrateShort({ type: 'light' })
        setTimeout(() => this.setData({ logCopied: false }), 2500)
      },
    })
  },

  copyAnalysis() {
    const text = this.data.analysisText
    if (!text) return
    wx.setClipboardData({
      data: text,
      success: () => {
        this.setData({ copied: true })
        setTimeout(() => this.setData({ copied: false }), 2500)
      },
    })
  },
})
