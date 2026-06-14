# 业财融合 Agent —— 技能开发指南

> 目标：让"给 Agent 加一项新能力"成为一件 10 分钟、低风险、可复制的事。
> 适用对象：财务驾驶舱（`/cockpit`）里的业财融合对话 Agent。

## 1. 它是怎么工作的（30 秒心智模型）

对话 Agent（`cockpit_ai_chat_stream`）每轮只看见三样东西：

1. **系统人设** `_COCKPIT_CHAT_SYSTEM`（口径、风格、防幻觉规则）；
2. **当前期间的数据快照**（`_build_cockpit_data_pack` 注入的上下文）；
3. **已注册的技能**（function-calling 工具 + 一句话能力概览）。

它**不会**凭空知道任何"快照之外"的数据或动作——想让它会，就给它注册一个**技能**。
技能一旦用 `@register_skill` 声明，会被**自动**：
列进 `/cockpit/skills` ｜ 写进系统提示（`skills_brief()`）｜ 暴露成 LLM 工具（`agent_tools()`）。
**无需改对话循环、无需改任何注册表。**

```
用户提问 ──► LLM（带 tools） ──► 决定调用某技能? ──► 执行 handler ──► 结果回灌 ──► LLM 继续作答
                 ▲                                                                     │
                 └─────────────────────── 工具循环上限 4 轮 ◄──────────────────────────┘
```

## 2. 技能契约

```python
@agent_skills.register_skill(
    name,          # 唯一英文标识，LLM 按它调用，如 'query_financials'
    label,         # 中文短名，UI/事件展示用，如 '查询经营业绩'
    desc,          # 给 LLM 看的能力说明——写清「什么时候该调用我」
    params,        # {参数名: 说明}；说明里含「必填」二字 => 该参数 required
    tool=False,    # True=暴露给 LLM 自动调用；破坏性操作务必 False（见 §4 安全）
    terminal=False,# True=该技能的输出即最终答案（如生成报告），命中后直接返回
    stream_handler=None,  # 终止型技能的流式生成器 (request,args)->yield (kind,delta)
)
def _skill_xxx(request, args):
    ...
    return {'ok': True, 'data': <可被 json 序列化的结果，字符串/字典皆可>}
    # 失败：return {'ok': False, 'error': '原因'}
```

`data` 会被 `json.dumps` 后回灌给 LLM，所以**返回 LLM 看得懂的文本或结构**即可。

## 3. 三类技能 + 可直接抄的模板

### A. 查询型（只读，最常用）——让 Agent 能"翻账"
照搬本仓库 `query_financials / query_receivables / query_project_margin` 的范式：

```python
@agent_skills.register_skill(
    'query_inventory', '查询库存', '查询指定期间/事业部的库存与周转，问到上下文外数据时调用',
    {'year': '年份（可选，默认当前对话期间）',
     'month': '月份1-12（可选，默认当前对话期间）',
     'bu': '事业部名称（可选，默认当前范围；无权访问将被忽略）'},
    tool=True)
def _skill_query_inventory(request, args):
    year, month, bus = _resolve_query_args(request, args)   # ← 复用：缺省取期间 + 权限收敛
    text = _build_inventory_summary(bus, year, month)        # ← 复用你已有的口径构造器
    return {'ok': True, 'data': text or '（该期间/范围无库存数据）'}
```

要点：**口径复用现成构造器**（别另造一套数字）；期间/范围一律走 `_resolve_query_args`。

### B. 动作型（有副作用，写入/修改）
参考 `save_knowledge`。**破坏性动作（删除/不可逆修改）请设 `tool=False`**，
只允许经 `/cockpit/skills/run` 显式触发，不让 LLM 自动调用。

### C. 终止型（输出即答案，通常要流式）
参考 `generate_report`：设 `terminal=True` + 提供 `stream_handler`，
命中后直接把其流式输出当最终回答推给前端。

## 4. 安全清单（每次加技能必过）

- [ ] **事业部权限收敛**：凡涉及 bu 的，必须经 `_resolve_query_args` 或
      `_can_access_bu(request, bu)` 校验，杜绝越权读到无权访问的事业部。
- [ ] **破坏性 = `tool=False`**：删除/批量改等不可逆动作不暴露给 LLM 自动调用。
- [ ] **handler 不抛裸异常**：内部 try/except，失败返回 `{'ok': False, 'error': ...}`；
      对话循环虽有兜底，但自管错误信息更友好。
- [ ] **无数据要兜底**：返回如 `'（该期间/范围无数据）'` 而不是空串或报错，
      让 LLM 知道"查过了但没有"，而非以为工具坏了。
- [ ] **只读优先**：能只读解决就别写库。

## 5. 测试范式

在 `caiwu/tests.py::CaiwuMetricsAndTargetsTests` 里照抄
`test_agent_readonly_query_skills`：经 `/cockpit/skills/run` 直接执行 handler
（不依赖 LLM），断言"在技能列表里 + 能按期间/事业部取数 + 无数据兜底不崩"。
涉及对话流式的，参考 `test_chat_function_calling_*`：mock `_deepseek_stream_raw`
为生成器，yield `('answer', delta)...` 再 yield `('final', {'content','tool_calls'})`。

## 6. 相关文件速查

| 作用 | 位置 |
|---|---|
| 注册表 / `agent_tools` / `skills_brief` | `caiwu/agent_skills.py` |
| 技能实现（含模型与权限上下文） | `caiwu/views.py`（搜 `@agent_skills.register_skill`） |
| 对话循环（function-calling + 真流式） | `caiwu/views.py::cockpit_ai_chat_stream` |
| 系统人设 / 数据上下文 | `_COCKPIT_CHAT_SYSTEM` / `_build_cockpit_data_pack` |
| LLM 调用封装 | `_deepseek_stream_raw`（流式+工具）/ `_deepseek_chat`(_raw) / `_deepseek_stream` |

---
往"顶级 Agent"演进的下一步候选：① 更多只读查询工具（覆盖全部数据域）；
② 工具调用的可观测性（把每步工具名/耗时落日志）；③ 让 Agent 能跨期间自主多步取数后再综合。
