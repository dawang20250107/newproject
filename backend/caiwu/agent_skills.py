"""业财融合 Agent 技能注册表（为后续给 Agent 增加可调用技能/工具预留）。

设计目标：让"加技能"成为一件低成本的事——后续只需用 @register_skill 声明一个
技能（名称/标签/说明/参数）并实现 handler(request, args)->{'ok':bool,'data'|'error'}，
即可：①在对话里向 LLM 声明该能力；②经 /cockpit/skills 列出、/cockpit/skills/run 执行；
③（后续）接入 LLM function-calling，实现"对话即操作"。

具体技能在 caiwu/views.py 里注册（那里有模型与权限上下文），此处只提供纯注册表，
避免循环依赖。

▶ 想给 Agent 加一项新能力？看同目录 AGENT_SKILLS.md（10 分钟、含可抄模板与安全清单）。"""

_REGISTRY = {}


def register_skill(name, label, desc, params=None, tool=False, terminal=False,
                   stream_handler=None, gate=None):
    """声明一个 Agent 技能。
    params: {参数名: 说明} 轻量 schema（说明含「必填」者计为 required）。
    tool:   是否暴露为 LLM 可自动调用的 function（function-calling）。破坏性技能应置 False。
    terminal: 该技能的输出即最终回答（如生成报告）；命中后直接把其结果作为答案返回。
    stream_handler: 终止型技能的流式生成器 (request, args) -> yield (kind, delta)。
    gate:   门控标签（如 'web'）；门控关闭时该技能不对 LLM/技能清单暴露、不可经统一入口执行。"""
    def deco(fn):
        _REGISTRY[name] = {
            'name': name, 'label': label, 'desc': desc,
            'params': params or {}, 'handler': fn,
            'tool': tool, 'terminal': terminal, 'stream_handler': stream_handler,
            'gate': gate,
        }
        return fn
    return deco


def _gate_open(gate):
    """技能门控判定：无门控恒开；'web' 门控随 settings.ENABLE_WEB_RESEARCH 开合。"""
    if not gate:
        return True
    from django.conf import settings
    if gate == 'web':
        return bool(getattr(settings, 'ENABLE_WEB_RESEARCH', False))
    return True


def skill_enabled(name):
    """技能是否存在且门控开启（供统一执行入口做准入校验）。"""
    s = _REGISTRY.get(name)
    return bool(s) and _gate_open(s.get('gate'))


def agent_tools():
    """把标记 tool=True 的技能转成 OpenAI/DeepSeek function-calling 的 tools 规格。"""
    out = []
    for s in _REGISTRY.values():
        if not s.get('tool') or not _gate_open(s.get('gate')):
            continue
        props, required = {}, []
        for p, d in s['params'].items():
            props[p] = {'type': 'string', 'description': d}
            if '必填' in d:
                required.append(p)
        out.append({'type': 'function', 'function': {
            'name': s['name'], 'description': s['desc'],
            'parameters': {'type': 'object', 'properties': props, 'required': required},
        }})
    return out


def list_skills():
    """对外暴露的技能清单（不含 handler）；门控关闭的技能不列出。"""
    return [{'name': s['name'], 'label': s['label'], 'desc': s['desc'], 'params': s['params']}
            for s in _REGISTRY.values() if _gate_open(s.get('gate'))]


def get_skill(name):
    return _REGISTRY.get(name)


def skills_brief():
    """一句话技能概览，注入对话系统提示，让助手知道自己有哪些能力。"""
    if not _REGISTRY:
        return ''
    return '；'.join(f"{s['label']}（{s['name']}）"
                    for s in _REGISTRY.values() if _gate_open(s.get('gate')))
