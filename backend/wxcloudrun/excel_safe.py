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


def excel_safe(v):
    """单值转义：以公式前缀开头的字符串前置单引号；非字符串/空串原样返回。"""
    if isinstance(v, str) and v and v[0] in _FORMULA_PREFIXES:
        return "'" + v
    return v


def sanitize_workbook(wb):
    """对整个 openpyxl 工作簿的所有单元格就地施加公式注入防护。"""
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                v = cell.value
                if isinstance(v, str) and v and v[0] in _FORMULA_PREFIXES:
                    if v[0] == '=' and _SAFE_FORMULA.match(v):
                        continue   # 应用自建纯数学聚合公式，安全放行
                    cell.value = "'" + v
    return wb
