const tcbConfig = require('./utils/tcbconfig.js');

App({
  globalData: {
    apiBase: 'https://kxtshare.cloud',
    userInfo: null,
    tcbEnvId: tcbConfig.ENV_ID,
  },
  onLaunch() {
    console.log('KXT 小程序启动');
    // 初始化腾讯云 CloudBase 云开发
    if (wx.cloud) {
      wx.cloud.init({
        env: tcbConfig.ENV_ID,
        traceUser: true,
      });
      console.log('CloudBase 初始化完成，环境:', tcbConfig.ENV_ID);
    }
  },
});
