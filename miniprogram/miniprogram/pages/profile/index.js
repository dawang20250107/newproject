const { request } = require('../../utils/request')

Page({
  data: {
    display_name: '',
    dept: '',
    role: '',
    name: '',
    avatarChar: '?',
    isDirty: false,
    isSaving: false,
  },

  onShow() { this._load() },

  async _load() {
    try {
      const r = await request('/api/profile')
      const p = r.profile || {}
      this.setData({
        display_name: p.display_name || '',
        dept: p.dept || '',
        role: p.role || '',
        name: p.name || '',
        avatarChar: this._getChar(p.name || p.display_name),
        isDirty: false,
      })
    } catch (e) {
      wx.showToast({ title: '加载失败', icon: 'none' })
    }
  },

  _getChar(str) {
    if (!str) return '?'
    return str.trim().charAt(0) || '?'
  },

  onInput(e) {
    const field = e.currentTarget.dataset.field
    const val = e.detail.value
    const update = { [field]: val, isDirty: true }
    if (field === 'name') {
      update.avatarChar = this._getChar(val || this.data.display_name)
    } else if (field === 'display_name') {
      update.avatarChar = this._getChar(this.data.name || val)
    }
    this.setData(update)
  },

  async onSave() {
    if (this.data.isSaving) return
    this.setData({ isSaving: true })
    try {
      const r = await request('/api/profile', {
        method: 'PUT',
        data: {
          display_name: this.data.display_name,
          dept: this.data.dept,
          role: this.data.role,
          name: this.data.name,
        },
      })
      const app = getApp()
      app.globalData.profile = r.profile
      wx.setStorageSync('kxt_profile', r.profile)
      this.setData({ isDirty: false, isSaving: false })
      wx.showToast({ title: '已保存 ✓', icon: 'success' })
    } catch (e) {
      this.setData({ isSaving: false })
      wx.showToast({ title: '保存失败', icon: 'none' })
    }
  },
})
