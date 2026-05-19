const { request } = require('../../utils/request')

function pad(n) { return n < 10 ? '0' + n : '' + n }
function fmtDate(d) { return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) }
function todayStr() { return fmtDate(new Date()) }

Page({
  data: {
    tab: 'edit',            // edit | calendar | week
    date: todayStr(),       // 当前编辑的日期
    blocks: [],             // [{ start, end, tasks: [{ desc, progress }] }]
    works: '',
    not_works: '',
    plans: '',
    commit_text: '',
    isDirty: false,
    isSaving: false,
    updatedAt: null,

    // 日历
    calYear: new Date().getFullYear(),
    calMonth: new Date().getMonth() + 1,
    calCells: [],           // [{ day, dateStr, hasReport, isToday, isCurMonth }]
    calDates: [],

    // 周分析
    weekData: null,
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
      this.setData({
        date: r.date,
        blocks: r.blocks || [],
        works: r.works || '',
        not_works: r.not_works || '',
        plans: r.plans || '',
        commit_text: r.commit_text || '',
        isDirty: false,
        updatedAt: r.updated_at,
      })
    } catch (e) {
      wx.showToast({ title: '加载失败', icon: 'none' })
    }
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
    this.setData({ blocks, isDirty: true })
  },

  removeBlock(e) {
    const i = e.currentTarget.dataset.i
    const blocks = this.data.blocks.slice()
    blocks.splice(i, 1)
    this.setData({ blocks, isDirty: true })
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
    this.setData({ blocks, isDirty: true })
  },

  removeTask(e) {
    const { i, j } = e.currentTarget.dataset
    const blocks = this.data.blocks.slice()
    const tasks = blocks[i].tasks.slice()
    tasks.splice(j, 1)
    blocks[i] = Object.assign({}, blocks[i], { tasks })
    this.setData({ blocks, isDirty: true })
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
    this.setData({ blocks, isDirty: true })
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
    // 周一为第一天: getDay() Sunday=0, Monday=1...
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
})
