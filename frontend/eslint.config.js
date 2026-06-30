// ESLint 9 扁平配置（flat config）。聚焦「能挡 bug」的静态检查：
// no-undef（拼错的后端字段/全局名静默 undefined 是无类型纯 JS 的最大隐患）、
// no-unused-vars（死代码/漏用）。格式化交给 Prettier，故用 eslint-config-prettier 关掉风格类规则。
// 安装：npm install 后 `npm run lint`。
import js from '@eslint/js'
import pluginVue from 'eslint-plugin-vue'
import globals from 'globals'
import prettier from 'eslint-config-prettier'

export default [
  {
    ignores: [
      'dist/**',
      'node_modules/**',
      '../backend/frontend_dist/**',
    ],
  },
  js.configs.recommended,
  ...pluginVue.configs['flat/recommended'],
  prettier,
  {
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: {
        ...globals.browser,
        ...globals.es2021,
      },
    },
    rules: {
      // 拼错的标识符/未定义全局 → 报错（无 TS 时最关键的一道网；当前全仓 0 命中，理想门禁）
      'no-undef': 'error',
      // 未使用变量/参数 → 警告（揪死代码/漏用）；以 _ 开头的有意忽略
      'no-unused-vars': ['warn', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      // 直接改 prop 是真实反模式 → 保留为警告，作为可逐步偿还的清单（非阻塞）
      'vue/no-mutating-props': 'warn',
      // 中文全角空格(U+3000)在本仓库（含 Vue 模板文本）是合法排版，整体关闭以免噪音
      'no-irregular-whitespace': 'off',
      // 有意的空 cat{} 静默忽略（项目大量「尽力而为」式 catch）
      'no-empty': ['warn', { allowEmptyCatch: true }],
      // 以下为纯格式/教条规则，交给 Prettier 或对内部工具无价值 → 关闭
      'vue/multi-word-component-names': 'off',
      'vue/no-v-html': 'off',
      'vue/require-default-prop': 'off',
      'vue/attributes-order': 'off',
      'vue/v-on-event-hyphenation': 'off',
      'vue/first-attribute-linebreak': 'off',
      'vue/html-self-closing': 'off',
      'vue/max-attributes-per-line': 'off',
      'vue/singleline-html-element-content-newline': 'off',
    },
  },
]
