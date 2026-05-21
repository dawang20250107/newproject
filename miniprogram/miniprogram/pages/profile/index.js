const { request } = require('../../utils/request')

Page({
  data: {
    display_name: '',
    dept: '',
    role: '',
    name: '',
    avatar: '',
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
        avatar: p.avatar || '',
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

  onChooseAvatar(e) {
    const url = e.detail && e.detail.avatarUrl
    if (!url) return
    wx.compressImage({
      src: url,
      quality: 60,
      compressedWidth: 200,
      success: (cr) => this._readAvatar(cr.tempFilePath),
      fail: () => this._readAvatar(url),
    })
  },

  _readAvatar(path) {
    wx.getFileSystemManager().readFile({
      filePath: path,
      encoding: 'base64',
      success: (res) => {
        this.setData({ avatar: 'data:image/jpeg;base64,' + res.data, isDirty: true })
      },
      fail: () => wx.showToast({ title: '头像读取失败', icon: 'none' }),
    })
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
          avatar: this.data.avatar,
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
