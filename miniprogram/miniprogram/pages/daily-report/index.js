// pages/daily-report/index.js
const { get, put } = require('../../utils/request.js');

// ─── 纯函数工具 ────────────────────────────────────────────
function todayISO() {
  const d = new Date(), pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function nowHHMM() {
  const d = new Date();
  return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
}

function formatDate(iso) {
  if (!iso) return '';
  const [, m, d] = iso.split('-').map(Number);
  return `${m}月${d}日`;
}

function computeDuration(start, end) {
  if (!start || !end) return '';
  const [sh, sm] = start.split(':').map(Number);
  const [eh, em] = end.split(':').map(Number);
  const mins = (eh * 60 + em) - (sh * 60 + sm);
  if (mins <= 0) return '';
  const h = Math.floor(mins / 60), m = mins % 60;
  if (h === 0) return m + 'min';
  if (m === 0) return h + 'h';
  return `${h}h${m}min`;
}

function fmtSlot(start, end) {
  const strip = t => parseInt(t.split(':')[0], 10) + ':' + t.split(':')[1];
  return strip(start) + '-' + strip(end);
}

function statusOf(p) {
  p = Math.min(Math.max(Number(p) || 0, 0), 100);
  return p >= 100 ? '已完成' : `未完成 ${p}%`;
}

function clamp(n, lo, hi) {
  return Math.min(Math.max(Number(n) || 0, lo), hi);
}

function isoDate(d) {
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function buildCalCells(year, month, reportDates) {
  const firstDay = new Date(year, month - 1, 1);
  const daysInMonth = new Date(year, month, 0).getDate();
  const today = todayISO();

  let startDow = firstDay.getDay();
  startDow = (startDow + 6) % 7; // Monday=0

  const pad = n => String(n).padStart(2, '0');
  const cells = [];

  for (let i = 0; i < startDow; i++) {
    const d = new Date(year, month - 1, i - startDow + 1);
    cells.push({ date: isoDate(d), day: d.getDate(), inMonth: false, hasReport: false, isToday: false });
  }
  for (let d = 1; d <= daysInMonth; d++) {
    const date = `${year}-${pad(month)}-${pad(d)}`;
    cells.push({
      date, day: d, inMonth: true,
      hasReport: reportDates.indexOf(date) >= 0,
      isToday: date === today,
    });
  }
  const rem = (7 - (cells.length % 7)) % 7;
  for (let i = 1; i <= rem; i++) {
    const d = new Date(year, month, i);
    cells.push({ date: isoDate(d), day: i, inMonth: false, hasReport: false, isToday: false });
  }
  return cells;
}

// ─── Page ────────────────────────────────────────────────
Page({
  data: {
    dept: '', role: '', name: '',
    date: '',
    blocks: [],
    works: '', notWorks: '', plans: '',
    commit: '--我承诺明天创造更高效的结果！',
    previewDept: '', previewLog: '',
    activeTab: 'edit',

    // 保存状态
    isDirty: false,
    isSaving: false,
    savedAt: '',

    // 日历
    calYear: 0,
    calMonth: 0,
    calCells: [],
    calLoading: false,

    // 周分析
    weekAnchor: '',
    weekData: null,
    weekLoading: false,
  },

  onLoad() {
    const now = new Date();
    this.setData({
      date: todayISO(),
      calYear: now.getFullYear(),
      calMonth: now.getMonth() + 1,
      weekAnchor: todayISO(),
    });
    this._loadFromServer();
  },

  // ── Tab 切换 ──────────────────────────────────────────
  switchTab(e) {
    const tab = e.currentTarget.dataset.tab;
    this.setData({ activeTab: tab });
    if (tab === 'preview') this._generate();
    if (tab === 'calendar') this._loadCalendar();
    if (tab === 'week') this._loadWeek();
    wx.pageScrollTo({ scrollTop: 0, duration: 0 });
  },

  // ── 基本信息输入 ──────────────────────────────────────
  onFieldInput(e) {
    const field = e.currentTarget.dataset.field;
    this.setData({ [field]: e.detail.value, isDirty: true });
    this._generate();
  },

  onDateChange(e) {
    this.setData({ date: e.detail.value, isDirty: false, savedAt: '' });
    this._loadFromServer();
  },

  // ── 时段操作 ──────────────────────────────────────────
  addBlock() {
    const blocks = this.data.blocks.slice();
    blocks.push({ start: '', end: '', duration: '', tasks: [{ desc: '', progress: 0 }] });
    this.setData({ blocks, isDirty: true });
  },

  removeBlock(e) {
    const idx = Number(e.currentTarget.dataset.index);
    const blocks = this.data.blocks.slice();
    blocks.splice(idx, 1);
    this.setData({ blocks, isDirty: true });
    this._generate();
  },

  onBlockTimeChange(e) {
    const { blockIndex, field } = e.currentTarget.dataset;
    const bi = Number(blockIndex);
    const blocks = this.data.blocks.slice();
    blocks[bi][field] = e.detail.value;
    blocks[bi].duration = computeDuration(blocks[bi].start, blocks[bi].end);
    this.setData({ blocks, isDirty: true });
    this._generate();
  },

  setNow(e) {
    const { blockIndex, field } = e.currentTarget.dataset;
    const bi = Number(blockIndex);
    const blocks = this.data.blocks.slice();
    const now = nowHHMM();
    const cur = blocks[bi][field];
    blocks[bi][field] = (!cur || now >= cur) ? now : cur;
    blocks[bi].duration = computeDuration(blocks[bi].start, blocks[bi].end);
    this.setData({ blocks, isDirty: true });
    this._generate();
  },

  // ── 任务操作 ──────────────────────────────────────────
  addTask(e) {
    const bi = Number(e.currentTarget.dataset.blockIndex);
    const blocks = this.data.blocks.slice();
    blocks[bi].tasks.push({ desc: '', progress: 0 });
    this.setData({ blocks, isDirty: true });
  },

  removeTask(e) {
    const bi = Number(e.currentTarget.dataset.blockIndex);
    const ti = Number(e.currentTarget.dataset.taskIndex);
    const blocks = this.data.blocks.slice();
    blocks[bi].tasks.splice(ti, 1);
    if (blocks[bi].tasks.length === 0) blocks[bi].tasks.push({ desc: '', progress: 0 });
    this.setData({ blocks, isDirty: true });
    this._generate();
  },

  onTaskInput(e) {
    const bi = Number(e.currentTarget.dataset.blockIndex);
    const ti = Number(e.currentTarget.dataset.taskIndex);
    const blocks = this.data.blocks.slice();
    blocks[bi].tasks[ti].desc = e.detail.value;
    this.setData({ blocks, isDirty: true });
    this._generate();
  },

  onProgressChanging(e) {
    const bi = Number(e.currentTarget.dataset.blockIndex);
    const ti = Number(e.currentTarget.dataset.taskIndex);
    const val = Math.round(e.detail.value);
    const blocks = this.data.blocks.slice();
    blocks[bi].tasks[ti].progress = val;
    this.setData({ blocks });
  },

  onProgressChange(e) {
    const bi = Number(e.currentTarget.dataset.blockIndex);
    const ti = Number(e.currentTarget.dataset.taskIndex);
    const val = clamp(Math.round(e.detail.value), 0, 100);
    const blocks = this.data.blocks.slice();
    blocks[bi].tasks[ti].progress = val;
    this.setData({ blocks, isDirty: true });
    this._generate();
  },

  markDone(e) {
    const bi = Number(e.currentTarget.dataset.blockIndex);
    const ti = Number(e.currentTarget.dataset.taskIndex);
    const blocks = this.data.blocks.slice();
    blocks[bi].tasks[ti].progress = 100;
    this.setData({ blocks, isDirty: true });
    this._generate();
    wx.showToast({ title: '✓ 已完成', icon: 'none', duration: 800 });
  },

  // ── 清空 ──────────────────────────────────────────────
  clearAll() {
    wx.showModal({
      title: '确认清空',
      content: '清空所有时段和任务？基本信息会保留。',
      confirmText: '清空',
      confirmColor: '#c96342',
      success: (res) => {
        if (!res.confirm) return;
        this.setData({
          blocks: [{ start: '', end: '', duration: '', tasks: [{ desc: '', progress: 0 }] }],
          isDirty: true,
        });
        this._generate();
      }
    });
  },

  // ── 保存按钮 ──────────────────────────────────────────
  onSave() {
    if (!this.data.isDirty || this.data.isSaving) return;
    this.setData({ isSaving: true });
    const { dept, role, name, date, blocks, works, notWorks, plans, commit } = this.data;
    put(`/api/daily-report/${date}`, { dept, role, name, blocks, works, not_works: notWorks, plans, commit })
      .then((res) => {
        const savedAt = res && res.updated_at ? res.updated_at.substring(11, 16) : '';
        this.setData({ isSaving: false, isDirty: false, savedAt });
        wx.showToast({ title: '已保存', icon: 'success', duration: 1200 });
        // refresh calendar dot
        const { calYear, calMonth } = this.data;
        const [y, m] = date.split('-').map(Number);
        if (y === calYear && m === calMonth) {
          this._loadCalendar();
        }
      })
      .catch((err) => {
        this.setData({ isSaving: false });
        wx.showToast({ title: err.message || '保存失败', icon: 'none' });
      });
  },

  // ── 复制 ──────────────────────────────────────────────
  copyDept() {
    const text = this.data.previewDept;
    if (!text.trim()) { wx.showToast({ title: '暂无内容', icon: 'none' }); return; }
    wx.setClipboardData({ data: text, success: () => wx.showToast({ title: '已复制部门群版', icon: 'success' }) });
  },

  copyLog() {
    const text = this.data.previewLog;
    if (!text.trim()) { wx.showToast({ title: '暂无内容', icon: 'none' }); return; }
    wx.setClipboardData({ data: text, success: () => wx.showToast({ title: '已复制日志群版', icon: 'success' }) });
  },

  // ── 生成预览 ─────────────────────────────────────────
  _generate() {
    const { dept, role, name, date, blocks, works, notWorks, plans, commit } = this.data;
    const dateStr = formatDate(date);
    const validBlocks = blocks.filter(b => b.start && b.end && b.tasks.some(t => t.desc.trim()));

    const deptLines = [`${name}   ${dateStr}：`];
    validBlocks.forEach((b, i) => {
      const dur = computeDuration(b.start, b.end);
      deptLines.push(`${i + 1}、${fmtSlot(b.start, b.end)}（用时${dur}）`);
      b.tasks.filter(t => t.desc.trim()).forEach(t => {
        deptLines.push(`    •${t.desc}（${statusOf(t.progress)}）`);
      });
    });

    const logLines = [`${dept}   ${role}  ${name}    ${dateStr}：`];
    validBlocks.forEach((b, i) => {
      logLines.push(`${i + 1}、${fmtSlot(b.start, b.end)}`);
      b.tasks.filter(t => t.desc.trim()).forEach(t => {
        logLines.push(`    •${t.desc}（${statusOf(t.progress)}）`);
      });
    });
    logLines.push('');
    logLines.push(`行得通的是：${works.trim() || '无'}`);
    logLines.push(`行不通的是：${notWorks.trim() || '无'}`);
    logLines.push('明日计划：');
    const plansArr = plans.split('\n').map(s => s.trim()).filter(Boolean);
    if (!plansArr.length) {
      logLines.push('1、？');
    } else {
      plansArr.forEach((p, i) => { logLines.push(`${i + 1}、${p.replace(/^\s*\d+[、.\)]\s*/, '')}`); });
    }
    if (commit.trim()) logLines.push(commit.trim());

    this.setData({ previewDept: deptLines.join('\n'), previewLog: logLines.join('\n') });
  },

  // ── 从服务器加载 ──────────────────────────────────────
  _loadFromServer() {
    const date = this.data.date;
    wx.showLoading({ title: '加载中...', mask: true });
    get(`/api/daily-report/${date}`, {}, { silent: true })
      .then((data) => {
        const blocks = (data.blocks || []).map(b => ({
          ...b,
          duration: computeDuration(b.start, b.end),
        }));
        this.setData({
          dept: data.dept || '',
          role: data.role || '',
          name: data.name || '',
          blocks: blocks.length ? blocks : [{ start: '', end: '', duration: '', tasks: [{ desc: '', progress: 0 }] }],
          works: data.works || '',
          notWorks: data.not_works || '',
          plans: data.plans || '',
          commit: data.commit || '--我承诺明天创造更高效的结果！',
          isDirty: false,
          savedAt: data.updated_at ? data.updated_at.substring(11, 16) : '',
        });
        this._generate();
      })
      .catch(() => {
        this.setData({
          blocks: [{ start: '', end: '', duration: '', tasks: [{ desc: '', progress: 0 }] }],
          isDirty: false,
          savedAt: '',
        });
      })
      .finally(() => {
        wx.hideLoading();
      });
  },

  // ── 日历 ─────────────────────────────────────────────
  _loadCalendar() {
    const { calYear, calMonth } = this.data;
    this.setData({ calLoading: true });
    get('/api/daily-report/list', { year: calYear, month: calMonth }, { silent: true })
      .then((data) => {
        const reportDates = (data && data.dates) ? data.dates : [];
        const calCells = buildCalCells(calYear, calMonth, reportDates);
        this.setData({ calCells, calLoading: false });
      })
      .catch(() => {
        const calCells = buildCalCells(calYear, calMonth, []);
        this.setData({ calCells, calLoading: false });
      });
  },

  onCalPrevMonth() {
    let { calYear, calMonth } = this.data;
    calMonth--;
    if (calMonth < 1) { calMonth = 12; calYear--; }
    this.setData({ calYear, calMonth });
    this._loadCalendar();
  },

  onCalNextMonth() {
    let { calYear, calMonth } = this.data;
    calMonth++;
    if (calMonth > 12) { calMonth = 1; calYear++; }
    this.setData({ calYear, calMonth });
    this._loadCalendar();
  },

  onCalCellTap(e) {
    const { date, inMonth } = e.currentTarget.dataset;
    if (!inMonth) return;
    this.setData({ date, activeTab: 'edit', isDirty: false, savedAt: '' });
    this._loadFromServer();
    wx.pageScrollTo({ scrollTop: 0, duration: 200 });
  },

  // ── 周分析 ─────────────────────────────────────────────
  _loadWeek() {
    const { weekAnchor } = this.data;
    this.setData({ weekLoading: true });
    get('/api/daily-report/week', { date: weekAnchor }, { silent: true })
      .then((data) => {
        this.setData({ weekData: data, weekLoading: false });
      })
      .catch(() => {
        this.setData({ weekLoading: false });
      });
  },

  onWeekPrev() {
    const d = new Date(this.data.weekAnchor);
    d.setDate(d.getDate() - 7);
    const weekAnchor = isoDate(d);
    this.setData({ weekAnchor });
    this._loadWeek();
  },

  onWeekNext() {
    const d = new Date(this.data.weekAnchor);
    d.setDate(d.getDate() + 7);
    const weekAnchor = isoDate(d);
    this.setData({ weekAnchor });
    this._loadWeek();
  },
});
