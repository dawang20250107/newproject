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
    allDone: false,

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
    weekCopied: false,

    // 汇报生成（部门群版 / 日志群版）
    showReport: false,
    reportTab: 'dept',
    deptText: '',
    logText: '',
    reportCopied: false,
  },

  onShow() {
    if (this.data.tab === 'edit') this._loadReport(this.data.date)
    else if (this.data.tab === 'calendar') this._loadCalendar()
    else if (this.data.tab === 'week') this._loadWeek()
  },

  switchTab(e) {
    const tab = e.currentTarget.dataset.tab
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
        commit_text: r.commit_text || '',
        isDirty: false,
        updatedAt: r.updated_at,
        allDone: this._computeAllDone(blocks),
      })
    } catch (e) {
      wx.showToast({ title: '加载失败', icon: 'none' })
    }
  },

  _computeAllDone(blocks) {
    if (!blocks || blocks.length === 0) return false
    let hasTask = false
    for (const blk of blocks) {
      for (const t of (blk.tasks || [])) {
        hasTask = true
        if ((t.progress || 0) < 100) return false
      }
    }
    return hasTask
  },

  pickDate(e) {
    const date = e.detail.value
    if (this.data.isDirty) {
      wx.showModal({
        title: '提示', content: '有未保存修改，确定切换日期？',
        success: (res) => { if (res.confirm) this.setData({ date }, () => this._loadReport(date)) }
      })
    } else {
      this.setData({ date }, () => this._loadReport(date))
    }
  },

  addBlock() {
    const blocks = this.data.blocks.concat([{ start: '09:00', end: '12:00', tasks: [] }])
    this.setData({ blocks, isDirty: true, allDone: this._computeAllDone(blocks) })
  },

  removeBlock(e) {
    const i = e.currentTarget.dataset.i
    const blocks = this.data.blocks.slice()
    blocks.splice(i, 1)
    this.setData({ blocks, isDirty: true, allDone: this._computeAllDone(blocks) })
  },

  onTimeChange(e) {
    const { i, field } = e.currentTarget.dataset
    const blocks = this.data.blocks.slice()
    blocks[i] = Object.assign({}, blocks[i], { [field]: e.detail.value })
    this.setData({ blocks, isDirty: true })
  },

  addTask(e) {
    const i = e.currentTarget.dataset.i
    const blocks = this.data.blocks.slice()
    blocks[i] = Object.assign({}, blocks[i], {
      tasks: (blocks[i].tasks || []).concat([{ desc: '', progress: 0 }])
    })
    this.setData({ blocks, isDirty: true, allDone: false })
  },

  removeTask(e) {
    const { i, j } = e.currentTarget.dataset
    const blocks = this.data.blocks.slice()
    const tasks = blocks[i].tasks.slice()
    tasks.splice(j, 1)
    blocks[i] = Object.assign({}, blocks[i], { tasks })
    this.setData({ blocks, isDirty: true, allDone: this._computeAllDone(blocks) })
  },

  onTaskInput(e) {
    const { i, j } = e.currentTarget.dataset
    const blocks = this.data.blocks.slice()
    const tasks = blocks[i].tasks.slice()
    tasks[j] = Object.assign({}, tasks[j], { desc: e.detail.value })
    blocks[i] = Object.assign({}, blocks[i], { tasks })
    this.setData({ blocks, isDirty: true })
  },

  onProgressChange(e) {
    const { i, j } = e.currentTarget.dataset
    const blocks = this.data.blocks.slice()
    const tasks = blocks[i].tasks.slice()
    tasks[j] = Object.assign({}, tasks[j], { progress: e.detail.value })
    blocks[i] = Object.assign({}, blocks[i], { tasks })
    this.setData({ blocks, isDirty: true, allDone: this._computeAllDone(blocks) })
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
    this.setData({ blocks, isDirty: true, allDone: this._computeAllDone(blocks) })
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
    this.setData({ blocks, isDirty: true, allDone: this._computeAllDone(blocks) })
    wx.vibrateShort({ type: 'medium' })
  },

  // 全局一键完成
  onAllDone() {
    const blocks = this.data.blocks.map(blk => ({
      ...blk,
      tasks: (blk.tasks || []).map(t => ({ ...t, progress: 100 })),
    }))
    this.setData({ blocks, isDirty: true, allDone: true })
    wx.vibrateShort({ type: 'heavy' })
    wx.showToast({ title: '全部完成 ✨', icon: 'none', duration: 1500 })
  },

  onTextInput(e) {
    const field = e.currentTarget.dataset.field
    this.setData({ [field]: e.detail.value, isDirty: true })
  },

  async onSave() {
    if (this.data.isSaving) return
    this.setData({ isSaving: true })
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
      this.setData({ isDirty: false, isSaving: false, updatedAt: res.updated_at })
      wx.showToast({ title: '已保存', icon: 'success' })
    } catch (e) {
      this.setData({ isSaving: false })
      wx.showToast({ title: '保存失败', icon: 'none' })
    }
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
      reportTab: 'dept',
      reportCopied: false,
      deptText: texts.deptText,
      logText: texts.logText,
    })
  },

  switchReportTab(e) {
    this.setData({ reportTab: e.currentTarget.dataset.rt, reportCopied: false })
  },

  closeReport() {
    this.setData({ showReport: false })
  },

  copyReport() {
    const text = this.data.reportTab === 'dept' ? this.data.deptText : this.data.logText
    if (!text) return
    wx.setClipboardData({
      data: text,
      success: () => {
        this.setData({ reportCopied: true })
        wx.vibrateShort({ type: 'light' })
        setTimeout(() => this.setData({ reportCopied: false }), 2500)
      },
    })
  },

  copyWeekReport() {
    const d = this.data.weekData
    if (!d) return
    const lines = [`【本周工作汇报】${d.week_start} ～ ${d.week_end}`,
      `总计 ${d.total_hours}h  完成任务 ${d.completed_count} 个`, '']
    for (const day of (d.days || [])) {
      if (!day.has_report) continue
      lines.push(`${day.date}（周${day.weekday}）${day.hours}h`)
      for (const t of (day.completed_tasks || [])) lines.push(`  ✓ ${t}`)
      lines.push('')
    }
    wx.setClipboardData({
      data: lines.join('\n').trim(),
      success: () => {
        this.setData({ weekCopied: true })
        setTimeout(() => this.setData({ weekCopied: false }), 2500)
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
