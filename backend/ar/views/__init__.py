# ar 视图层装配清单。
# 原 8692 行的单文件 ar/views.py 已按业务域拆分为本包下的子模块：
#   _common   共享导入 / 常量 / 通用权限·部门过滤·导出·日期助手 + 记录过滤助手簇
#   projects  项目台账          records   应收记录        analytics 分析
#   advances  预收预付          suppliers 供应商池        customers 客户
#   contracts 合同              budget    预算            invoices  合并开票批次
#   cashflow  资金对比          actions   行动项          pool      资金池
# 各域 `from ._common import *` 取得基座，互不直接依赖；本 __init__ 统一再导出，
# 保证 `from ar import views; views.X`、urls.py、signals、tests 等引用零改动。
from ._common import *   # noqa: F401,F403

from .projects import *   # noqa: F401,F403,E402
from .records import *    # noqa: F401,F403,E402
from .analytics import *  # noqa: F401,F403,E402
from .advances import *   # noqa: F401,F403,E402
from .suppliers import *  # noqa: F401,F403,E402
from .customers import *  # noqa: F401,F403,E402
from .contracts import *  # noqa: F401,F403,E402
from .budget import *     # noqa: F401,F403,E402
from .filter_schemes import *  # noqa: F401,F403,E402
from .invoices import *   # noqa: F401,F403,E402
from .cashflow import *   # noqa: F401,F403,E402
from .actions import *    # noqa: F401,F403,E402
from .pool import *       # noqa: F401,F403,E402
from .collection_logs import *   # noqa: F401,F403,E402
