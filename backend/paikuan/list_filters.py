"""Excel 风格「列头筛选 + 排序」的安全解析层。

前端把每列的筛选条件汇总成一个 JSON 参数 `filters` 传来，例如：

    filters = {
        "applicant":    {"op": "contains", "value": "张"},
        "amount":       {"op": "between",  "value": ["1000", "5000"]},
        "planned_date": {"op": "gte",      "value": "2025-01-01"},
        "status":       {"op": "in",       "value": ["pending", "approved"]}
    }

本模块把它解析成 Django ORM 的 Q 对象。**白名单驱动**：只有在列注册表
（registry）里登记过的字段、且运算符与该列类型匹配，才会进入 ORM——任何
未登记字段或非法运算符一律静默忽略，杜绝 ORM 注入与越权筛选。

排序同理：`resolve_sort` 只接受注册表中标记 sortable 的列。
"""

import json
import datetime
from decimal import Decimal, InvalidOperation

from django.db.models import Q

# 每种列类型允许的运算符（前端越界传入会被忽略）。对标金蝶云星空通用过滤：
# 文本支持 等于/不等于/包含/不包含/开头/结尾/为空/不为空 + 选值(in/not_in)；
# 数字与日期支持 为空/不为空；枚举支持 在/不在。
_TEXT_OPS = {'contains', 'eq', 'ne', 'not_contains', 'startswith', 'endswith',
             'empty', 'not_empty', 'in', 'not_in'}
_NUMBER_OPS = {'eq', 'ne', 'gt', 'lt', 'gte', 'lte', 'between', 'empty', 'not_empty'}
_DATE_OPS = {'eq', 'gte', 'lte', 'between', 'empty', 'not_empty'}
_ENUM_OPS = {'in', 'not_in'}

# 不需要 value 的「一元运算符」（为空/不为空）——需在空值守卫之前判定，否则会被跳过
_NULLARY_OPS = {'empty', 'not_empty'}


def _empty_q(col):
    """文本「为空」：NULL 或空串都算空。"""
    return Q(**{f'{col}__isnull': True}) | Q(**{col: ''})


def _num(v):
    try:
        return Decimal(str(v).strip())
    except (InvalidOperation, TypeError, ValueError, AttributeError):
        return None


def _date(v):
    try:
        return datetime.date.fromisoformat(str(v).strip()[:10])
    except (ValueError, TypeError, AttributeError):
        return None


def _pair(val):
    """区间值统一取 (lo, hi)，缺位补 None。"""
    if isinstance(val, (list, tuple)):
        lo = val[0] if len(val) > 0 else None
        hi = val[1] if len(val) > 1 else None
        return lo, hi
    return None, None


def build_filter_q(raw_json, registry):
    """把 filters JSON 解析为 (Q, needs_distinct)。

    registry: {field: {'type': 'text|number|date|enum', 'col': '<orm_lookup>',
                       'multi': bool(可选，反向关联字段需 .distinct())}}
    无法解析的子句静默跳过——筛选是「尽力而为」，绝不因脏输入报错中断列表。
    """
    q = Q()
    needs_distinct = False
    if not raw_json:
        return q, needs_distinct
    try:
        spec = json.loads(raw_json)
    except (ValueError, TypeError):
        return q, needs_distinct
    if not isinstance(spec, dict):
        return q, needs_distinct

    for field, clause in spec.items():
        meta = registry.get(field)
        if not meta or not isinstance(clause, dict):
            continue
        op = clause.get('op')
        val = clause.get('value')
        col = meta['col']
        t = meta['type']
        added = False

        # 一元运算符（为空/不为空）：文本/数字/日期通用，不读 value，最先处理
        if op in _NULLARY_OPS and (
                (t == 'text' and op in _TEXT_OPS) or
                (t == 'number' and op in _NUMBER_OPS) or
                (t == 'date' and op in _DATE_OPS)):
            empty = _empty_q(col) if t == 'text' else Q(**{f'{col}__isnull': True})
            q &= empty if op == 'empty' else ~empty
            added = True

        elif t == 'text' and op in _TEXT_OPS:
            # 选值清单（Excel 自动筛选）：in/not_in 取字符串数组
            if op in ('in', 'not_in'):
                vals = [str(x).strip() for x in val if str(x).strip()] if isinstance(val, (list, tuple)) else []
                if vals:
                    inq = Q(**{f'{col}__in': vals})
                    q &= inq if op == 'in' else ~inq
                    added = True
            else:
                s = str(val or '').strip()
                if not s:
                    continue
                if op == 'eq':
                    q &= Q(**{col: s})
                elif op == 'ne':
                    q &= ~Q(**{col: s})
                elif op == 'contains':
                    q &= Q(**{f'{col}__icontains': s})
                elif op == 'not_contains':
                    q &= ~Q(**{f'{col}__icontains': s})
                elif op == 'startswith':
                    q &= Q(**{f'{col}__istartswith': s})
                elif op == 'endswith':
                    q &= Q(**{f'{col}__iendswith': s})
                added = True

        elif t == 'number' and op in _NUMBER_OPS:
            if op == 'between':
                lo, hi = _pair(val)
                lo, hi = _num(lo), _num(hi)
                if lo is not None:
                    q &= Q(**{f'{col}__gte': lo})
                    added = True
                if hi is not None:
                    q &= Q(**{f'{col}__lte': hi})
                    added = True
            else:
                n = _num(val)
                if n is None:
                    continue
                if op == 'ne':
                    q &= ~Q(**{col: n})
                else:
                    q &= Q(**{(col if op == 'eq' else f'{col}__{op}'): n})
                added = True

        elif t == 'date' and op in _DATE_OPS:
            if op == 'between':
                lo, hi = _pair(val)
                lo, hi = _date(lo), _date(hi)
                if lo is not None:
                    q &= Q(**{f'{col}__gte': lo})
                    added = True
                if hi is not None:
                    q &= Q(**{f'{col}__lte': hi})
                    added = True
            else:
                d = _date(val)
                if d is None:
                    continue
                q &= Q(**{(col if op == 'eq' else f'{col}__{op}'): d})
                added = True

        elif t == 'enum' and op in _ENUM_OPS:
            vals = [str(x).strip() for x in val if str(x).strip()] if isinstance(val, (list, tuple)) else []
            if vals:
                inq = Q(**{f'{col}__in': vals})
                q &= inq if op == 'in' else ~inq
                added = True

        if added and meta.get('multi'):
            needs_distinct = True

    return q, needs_distinct


def resolve_sort(raw_sort, raw_order, registry):
    """解析排序字段，仅允许注册表中标记 sortable!=False 的列。

    返回可直接喂给 queryset.order_by(...) 的字符串；未指定或非法字段返回 None，
    由调用方回退到模型默认排序（保持原有列表顺序不被打乱）。
    """
    meta = registry.get((raw_sort or '').strip())
    if not meta or meta.get('sortable') is False:
        return None
    col = meta.get('sort_col') or meta['col']
    return f'-{col}' if (raw_order or '').strip().lower() == 'desc' else col
