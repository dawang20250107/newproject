"""业财融合 Agent 技能注册表（为后续给 Agent 增加可调用技能/工具预留）。

设计目标：让"加技能"成为一件低成本的事——后续只需用 @register_skill 声明一个
技能（名称/标签/说明/参数）并实现 handler(request, args)->{'ok':bool,'data'|'error'}，
即可：①在对话里向 LLM 声明该能力；②经 /cockpit/skills 列出、/cockpit/skills/run 执行；
③（后续）接入 LLM function-calling，实现"对话即操作"。

具体技能在 caiwu/views.py 里注册（那里有模型与权限上下文），此处只提供纯注册表，
避免循环依赖。"""

_REGISTRY = {}


def register_skill(name, label, desc, params=None):
    """声明一个 Agent 技能。params 为 {参数名: 说明} 的轻量 schema（用于展示/校验）。"""
    def deco(fn):
        _REGISTRY[name] = {
            'name': name, 'label': label, 'desc': desc,
            'params': params or {}, 'handler': fn,
        }
        return fn
    return deco


def list_skills():
    """对外暴露的技能清单（不含 handler）。"""
    return [{'name': s['name'], 'label': s['label'], 'desc': s['desc'], 'params': s['params']}
            for s in _REGISTRY.values()]


def get_skill(name):
    return _REGISTRY.get(name)


def skills_brief():
    """一句话技能概览，注入对话系统提示，让助手知道自己有哪些能力。"""
    if not _REGISTRY:
        return ''
    return '；'.join(f"{s['label']}（{s['name']}）" for s in _REGISTRY.values())
