"""Excel 公式注入（CSV/Excel Injection）防护，全系统共享单一实现。

用户可控文本若以 = + - @ 制表/回车 开头，会计在 Excel/WPS 打开导出文件时会被
当作公式执行（数据外带、命令执行等）。出口统一对这类文本前置单引号转义。

最佳实践：在「导出响应构建」这一出口 chokepoint 统一全表扫描，而非依赖每个
导出函数逐格自觉调用——后者一旦新增导出点就会漏。
"""

import re as _re
_FORMULA_PREFIXES = ('=', '+', '-', '@', '\t', '\r')
# 应用自建的纯数学聚合公式白名单：只引用单元格区域与算术符，无法外带数据/执行命令。
# 放行它们，让模板里的 =SUM(B5:M5) 正常计算；其余一律转义（含 =HYPERLINK/=cmd/=WEBSERVICE）。
_SAFE_FORMULA = _re.compile(r'^=(?:SUM|AVERAGE|ROUND|MIN|MAX|SUBTOTAL|ABS)\([A-Za-z0-9:,.\s+\-*/()]*\)$')
# 纯单元格算术/条件公式语法（经营情况表等模板行汇总用）：整条公式仅由 白名单函数
# 开括号、单元格引用、数字、算术/比较/分隔符 和唯一放行的字符串字面量 "-" 构成。
# 任何字母序列必须是白名单函数名或单元格引用才能匹配，无 & 拼接、无 ! 跨表、无其它
# 字符串字面量 → 无法构造 HYPERLINK/WEBSERVICE/DDE 等外带或执行载荷。
# 注意：语法合法只是必要条件——仅当单元格坐标也在导出函数登记的模板公式白名单
# （sanitize_workbook 的 safe_coords）中才放行，用户数据即使形如 =1+1 也一律转义。
_SAFE_MATH_FORMULA = _re.compile(
    r'^=(?:'
    r'(?:SUM|AVERAGE|ROUND|MIN|MAX|SUBTOTAL|ABS|IF|IFERROR|N)\('   # 白名单函数
    r'|\$?[A-Z]{1,3}\$?[0-9]{1,7}'                                 # 单元格引用
    r'|[0-9.]+'                                                    # 数字
    r'|"-"'                                                        # 字符串字面量仅放行 "-"
    r'|[+\-*/(),:<>= ]'                                            # 算术/比较/分隔
    r')+$'
)


def excel_safe(v):
    """单值转义：以公式前缀开头的字符串前置单引号；非字符串/空串原样返回。"""
    if isinstance(v, str) and v and v[0] in _FORMULA_PREFIXES:
        return "'" + v
    return v


def sanitize_workbook(wb, safe_coords=None):
    """对整个 openpyxl 工作簿的所有单元格就地施加公式注入防护。

    safe_coords：导出函数登记的模板公式坐标白名单 {(sheet标题, 'C4'), ...}。
    仅当坐标在名单内且公式通过纯算术语法校验才放行——按「作者」而非「长相」
    区分模板公式与用户数据，用户录入的 =1+1 之类照样转义。"""
    safe_coords = safe_coords or frozenset()
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                v = cell.value
                if isinstance(v, str) and v and v[0] in _FORMULA_PREFIXES:
                    if v[0] == '=' and _SAFE_FORMULA.match(v):
                        continue   # 应用自建纯数学聚合公式，安全放行
                    if (v[0] == '=' and (ws.title, cell.coordinate) in safe_coords
                            and _SAFE_MATH_FORMULA.match(v)):
                        continue   # 登记过坐标的模板算术公式
                    if v == '-':
                        continue   # 单独的占位横杠（0 值/不适用），无载荷
                    cell.value = "'" + v
    return wb
