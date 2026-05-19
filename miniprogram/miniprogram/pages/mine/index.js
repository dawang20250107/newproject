const api = require('../../utils/request.js');
const config = require('../../utils/config.js');

const AUTO_SYNC_INTERVAL = 3600000; // 1 小时
const SYNC_LOG_KEY = 'kxt_sync_logs';
const AUTO_SYNC_KEY = 'kxt_auto_sync';
const LAST_SYNC_KEY = 'kxt_last_sync';

Page({
  data: {
    syncing: false,
    lastSyncTime: '',
    syncResult: { type: '', msg: '' },
    autoSyncEnabled: false,
    syncLogs: [],
  },

  onShow() {
    this.loadPersistedState();
    this.startAutoSyncTimer();
  },

  onHide() {
    this.clearAutoSyncTimer();
  },

  onUnload() {
    this.clearAutoSyncTimer();
  },

  // ─── 加载持久化状态 ───
  loadPersistedState() {
    const lastSync = wx.getStorageSync(LAST_SYNC_KEY);
    const autoSync = wx.getStorageSync(AUTO_SYNC_KEY);
    const logs = wx.getStorageSync(SYNC_LOG_KEY) || [];
    this.setData({
      lastSyncTime: lastSync || '',
      autoSyncEnabled: !!autoSync,
      syncLogs: (Array.isArray(logs) ? logs : []).slice(0, 20),
    });
  },

  // ─── 自动同步开关 ───
  onToggleAutoSync(e) {
    const enabled = e.detail.value;
    wx.setStorageSync(AUTO_SYNC_KEY, enabled ? '1' : '');
    this.setData({ autoSyncEnabled: enabled });
    if (enabled) {
      this.startAutoSyncTimer();
      wx.showToast({ title: '自动同步已开启', icon: 'success' });
    } else {
      this.clearAutoSyncTimer();
      wx.showToast({ title: '自动同步已关闭', icon: 'none' });
    }
  },

  // ─── 自动同步定时器 ───
  _autoTimer: null,

  startAutoSyncTimer() {
    this.clearAutoSyncTimer();
    if (!this.data.autoSyncEnabled) return;
    // 立即执行一次同步，不等 1 小时间隔
    this.runSync();
    this._autoTimer = setInterval(() => {
      this.runSync();
    }, AUTO_SYNC_INTERVAL);
  },

  clearAutoSyncTimer() {
    if (this._autoTimer) {
      clearInterval(this._autoTimer);
      this._autoTimer = null;
    }
  },

  // ─── 手动同步 ───
  onManualSync() {
    if (this.data.syncing) return;
    wx.showModal({
      title: '确认同步',
      content: '将从腾讯文档拉取最新数据覆盖服务器，是否继续？',
      confirmText: '开始同步',
      confirmColor: '#2563eb',
      success: (res) => {
        if (!res.confirm) return;
        this.runSync();
      },
    });
  },

  // ─── 执行同步 ───
  async runSync() {
    if (this.data.syncing) return;
    this.setData({
      syncing: true,
      syncResult: { type: '', msg: '' },
    });
    wx.showLoading({ title: '同步中...', mask: true });

    try {
      const result = await api.post(config.API.SYNC_FROM_DOCS, {});

      // 记录同步时间
      const now = new Date();
      const timeStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')} ${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;

      wx.setStorageSync(LAST_SYNC_KEY, timeStr);

      const msg = result?.message || '同步完成';
      const logEntry = { time: timeStr, status: 'success', msg };

      // 更新日志
      const logs = [logEntry, ...this.data.syncLogs].slice(0, 20);
      wx.setStorageSync(SYNC_LOG_KEY, logs);

      this.setData({
        syncing: false,
        lastSyncTime: timeStr,
        syncLogs: logs,
        syncResult: { type: 'success', msg },
      });
      wx.showToast({ title: '同步成功', icon: 'success' });
    } catch (e) {
      console.error('同步失败', e);
      const errMsg = e?.message || e?.errMsg || '同步失败，请稍后重试';

      const now = new Date();
      const timeStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')} ${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;

      const logEntry = { time: timeStr, status: 'error', msg: errMsg };
      const logs = [logEntry, ...this.data.syncLogs].slice(0, 20);
      wx.setStorageSync(SYNC_LOG_KEY, logs);

      this.setData({
        syncing: false,
        syncLogs: logs,
        syncResult: { type: 'error', msg: errMsg },
      });
      wx.showToast({ title: '同步失败', icon: 'error' });
    } finally {
      wx.hideLoading();
    }
  },

  // ─── 清除日志 ───
  onClearLogs() {
    wx.showModal({
      title: '确认清除',
      content: '将清除所有同步日志记录，是否继续？',
      confirmText: '清除',
      confirmColor: '#dc2626',
      success: (res) => {
        if (!res.confirm) return;
        wx.setStorageSync(SYNC_LOG_KEY, []);
        this.setData({ syncLogs: [] });
        wx.showToast({ title: '已清除', icon: 'success' });
      },
    });
  },

  // ─── 复制 API 地址 ───
  onCopyApiUrl() {
    wx.setClipboardData({
      data: config.API_BASE,
      success: () => {
        wx.showToast({ title: '已复制', icon: 'success' });
      },
    });
  },
});
