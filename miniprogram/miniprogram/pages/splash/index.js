const app = getApp()

Page({
  data: {
    statusText: '正在连接...',
    tapCount: 0,
    pressed: false,
  },

  onLoad() {
    this._doLogin()
  },

  onTapSplash() {
    const count = this.data.tapCount + 1
    this.setData({ tapCount: count, pressed: true })
    wx.vibrateShort({ type: 'light' })
    setTimeout(() => this.setData({ pressed: false }), 200)
  },

  async _doLogin() {
    const minDelay = new Promise(resolve => setTimeout(resolve, 2200))
    try {
      await Promise.all([app._silentLogin(), minDelay])
      this.setData({ statusText: '进入中 ✨' })
      setTimeout(() => {
        wx.switchTab({ url: '/pages/report/index' })
      }, 400)
    } catch (e) {
      this.setData({ statusText: '网络异常，3秒后重试...' })
      setTimeout(() => {
        this.setData({ statusText: '正在重试...' })
        this._doLogin()
      }, 3000)
    }
  },
})
