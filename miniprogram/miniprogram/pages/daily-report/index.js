// pages/daily-report/index.js
const STORAGE_KEY = 'daily_report_v3_mp';

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

// ─── 默认示例数据 ─────────────────────────────────────────
const DEFAULT_BLOCKS = [
  {
    start: '08:30', end: '09:00',
    duration: '30min',
    tasks: [{ desc: '参加部门早会', progress: 100 }]
  },
  {
    start: '09:00', end: '10:00',
    duration: '1h',
    tasks: [{ desc: '与欣玉姐前往供应链现场，查看到岗人数以及人员安排和调整。', progress: 100 }]
  },
  {
    start: '10:00', end: '12:00',
    duration: '2h',
    tasks: [
      { desc: '督促项目负责人填写t-1天各项目金额数据表', progress: 100 },
      { desc: '根据现有的项目和行业，查找客户大同行、同行大客户', progress: 80 }
    ]
  },
];

// ─── Page ────────────────────────────────────────────────
Page({
  data: {
    dept: '劳务事业部',
    role: '财务BP',
    name: '王力平',
    date: '',
    blocks: [],
    works: '',
    notWorks: '',
    plans: '',
    commit: '--我承诺明天创造更高效的结果！',
    showWelcome: true,
    previewDept: '',
    previewLog: '',
    activeTab: 'edit',
  },

  onLoad() {
    this.setData({ date: todayISO() });
    this._load();
  },

  // ── 欢迎界面 ──────────────────────────────────────────
  onWelcomeConfirm() {
    this.setData({ showWelcome: false });
  },

  // ── Tab 切换 ──────────────────────────────────────────
  switchTab(e) {
    const tab = e.currentTarget.dataset.tab;
    this.setData({ activeTab: tab });
    if (tab === 'preview') this._generate();
    wx.pageScrollTo({ scrollTop: 0, duration: 0 });
  },

  // ── 基本信息输入 ──────────────────────────────────────
  onFieldInput(e) {
    const field = e.currentTarget.dataset.field;
    this.setData({ [field]: e.detail.value });
    this._generate();
    this._save();
  },

  onDateChange(e) {
    this.setData({ date: e.detail.value });
    this._generate();
    this._save();
  },

  // ── 时段操作 ──────────────────────────────────────────
  addBlock() {
    const blocks = this.data.blocks.slice();
    blocks.push({ start: '', end: '', duration: '', tasks: [{ desc: '', progress: 0 }] });
    this.setData({ blocks });
    this._save();
  },

  removeBlock(e) {
    const idx = Number(e.currentTarget.dataset.index);
    const blocks = this.data.blocks.slice();
    blocks.splice(idx, 1);
    this.setData({ blocks });
    this._generate();
    this._save();
  },

  // 时间 picker 改变
  onBlockTimeChange(e) {
    const { blockIndex, field } = e.currentTarget.dataset;
    const bi = Number(blockIndex);
    const blocks = this.data.blocks.slice();
    blocks[bi][field] = e.detail.value;
    blocks[bi].duration = computeDuration(blocks[bi].start, blocks[bi].end);
    this.setData({ blocks });
    this._generate();
    this._save();
  },

  // "现在"按钮
  setNow(e) {
    const { blockIndex, field } = e.currentTarget.dataset;
    const bi = Number(blockIndex);
    const blocks = this.data.blocks.slice();
    const now = nowHHMM();
    const cur = blocks[bi][field];
    blocks[bi][field] = (!cur || now >= cur) ? now : cur;
    blocks[bi].duration = computeDuration(blocks[bi].start, blocks[bi].end);
    this.setData({ blocks });
    this._generate();
    this._save();
  },

  // ── 任务操作 ──────────────────────────────────────────
  addTask(e) {
    const bi = Number(e.currentTarget.dataset.blockIndex);
    const blocks = this.data.blocks.slice();
    blocks[bi].tasks.push({ desc: '', progress: 0 });
    this.setData({ blocks });
    this._save();
  },

  removeTask(e) {
    const bi = Number(e.currentTarget.dataset.blockIndex);
    const ti = Number(e.currentTarget.dataset.taskIndex);
    const blocks = this.data.blocks.slice();
    blocks[bi].tasks.splice(ti, 1);
    if (blocks[bi].tasks.length === 0) {
      blocks[bi].tasks.push({ desc: '', progress: 0 });
    }
    this.setData({ blocks });
    this._generate();
    this._save();
  },

  onTaskInput(e) {
    const bi = Number(e.currentTarget.dataset.blockIndex);
    const ti = Number(e.currentTarget.dataset.taskIndex);
    const blocks = this.data.blocks.slice();
    blocks[bi].tasks[ti].desc = e.detail.value;
    this.setData({ blocks });
    this._generate();
    this._save();
  },

  // slider 拖动中（实时刷新 UI，不保存）
  onProgressChanging(e) {
    const bi = Number(e.currentTarget.dataset.blockIndex);
    const ti = Number(e.currentTarget.dataset.taskIndex);
    const val = Math.round(e.detail.value);
    const blocks = this.data.blocks.slice();
    blocks[bi].tasks[ti].progress = val;
    this.setData({ blocks });
  },

  // slider 松手（保存）
  onProgressChange(e) {
    const bi = Number(e.currentTarget.dataset.blockIndex);
    const ti = Number(e.currentTarget.dataset.taskIndex);
    const val = clamp(Math.round(e.detail.value), 0, 100);
    const blocks = this.data.blocks.slice();
    blocks[bi].tasks[ti].progress = val;
    this.setData({ blocks });
    this._generate();
    this._save();
  },

  markDone(e) {
    const bi = Number(e.currentTarget.dataset.blockIndex);
    const ti = Number(e.currentTarget.dataset.taskIndex);
    const blocks = this.data.blocks.slice();
    blocks[bi].tasks[ti].progress = 100;
    this.setData({ blocks });
    this._generate();
    this._save();
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
          blocks: [{ start: '', end: '', duration: '', tasks: [{ desc: '', progress: 0 }] }]
        });
        this._generate();
        this._save();
      }
    });
  },

  // ── 复制 ──────────────────────────────────────────────
  copyDept() {
    const text = this.data.previewDept;
    if (!text.trim()) { wx.showToast({ title: '暂无内容', icon: 'none' }); return; }
    wx.setClipboardData({
      data: text,
      success: () => wx.showToast({ title: '已复制部门群版', icon: 'success' })
    });
  },

  copyLog() {
    const text = this.data.previewLog;
    if (!text.trim()) { wx.showToast({ title: '暂无内容', icon: 'none' }); return; }
    wx.setClipboardData({
      data: text,
      success: () => wx.showToast({ title: '已复制日志群版', icon: 'success' })
    });
  },

  // ── 生成预览 ─────────────────────────────────────────
  _generate() {
    const { dept, role, name, date, blocks, works, notWorks, plans, commit } = this.data;
    const dateStr = formatDate(date);
    const validBlocks = blocks.filter(
      b => b.start && b.end && b.tasks.some(t => t.desc.trim())
    );

    // 部门群版（带用时）
    const deptLines = [`${name}   ${dateStr}：`];
    validBlocks.forEach((b, i) => {
      const dur = computeDuration(b.start, b.end);
      deptLines.push(`${i + 1}、${fmtSlot(b.start, b.end)}（用时${dur}）`);
      b.tasks.filter(t => t.desc.trim()).forEach(t => {
        deptLines.push(`    •${t.desc}（${statusOf(t.progress)}）`);
      });
    });

    // 日志群版（不带用时 + 复盘）
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
      plansArr.forEach((p, i) => {
        logLines.push(`${i + 1}、${p.replace(/^\s*\d+[、.\)]\s*/, '')}`);
      });
    }
    if (commit.trim()) logLines.push(commit.trim());

    this.setData({
      previewDept: deptLines.join('\n'),
      previewLog: logLines.join('\n'),
    });
  },

  // ── 存储 ─────────────────────────────────────────────
  _save() {
    const { dept, role, name, date, blocks, works, notWorks, plans, commit } = this.data;
    try {
      wx.setStorageSync(STORAGE_KEY, { dept, role, name, date, blocks, works, notWorks, plans, commit });
    } catch (e) { /* 忽略存储错误 */ }
  },

  _load() {
    try {
      const data = wx.getStorageSync(STORAGE_KEY);
      if (data && data.blocks) {
        const blocks = data.blocks.map(b => ({
          ...b,
          duration: computeDuration(b.start, b.end)
        }));
        this.setData({
          dept: data.dept || '劳务事业部',
          role: data.role || '财务BP',
          name: data.name || '王力平',
          date: todayISO(),
          blocks,
          works: data.works || '',
          notWorks: data.notWorks || '',
          plans: data.plans || '',
          commit: data.commit !== undefined ? data.commit : '--我承诺明天创造更高效的结果！',
        });
      } else {
        this.setData({ date: todayISO(), blocks: DEFAULT_BLOCKS });
      }
    } catch (e) {
      this.setData({ date: todayISO(), blocks: DEFAULT_BLOCKS });
    }
    this._generate();
  },
});
