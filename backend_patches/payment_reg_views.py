from rest_framework.views import APIView
from rest_framework.response import Response
from django.db import connection
from django.db.models import Sum, Count


class PaymentRegistrationView(APIView):
    """
    付款登记表 - 完整CRUD + 排序 + 过滤 + 月度筛选
    对应 payment_registrations 表（报销基础统计表数据）
    """

    def get(self, request):
        search = request.query_params.get('search', '').strip()
        is_paid = request.query_params.get('is_paid', '').strip()
        month_filter = request.query_params.get('month', '').strip()  # e.g. 2026-04
        source = request.query.params.get('source', '').strip()
        project_name = request.query_params.get('project_name', '').strip()
        manager = request.query_params.get('manager', '').strip()
        ordering = request.query_params.get('ordering', '-planned_date').strip()
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 20))

        where = ['1=1']
        params = []
        if search:
            where.append("(project_name LIKE %s OR applicant_name LIKE %s OR description LIKE %s)")
            p = f"%{search}%"
            params.extend([p, p, p])
        if is_paid == 'true' or is_paid == '1':
            where.append("is_paid = 1")
        elif is_paid == 'false' or is_paid == '0':
            where.append("is_paid = 0")
        if source:
            where.append("source_sheet = %s")
            params.append(source)
        if project_name:
            where.append("project_name = %s")
            params.append(project_name)
        if manager:
            where.append("payment_manager = %s")
            params.append(manager)
        if month_filter:
            where.append("DATE_FORMAT(planned_date, '%%Y-%%m') = %s")
            params.append(month_filter)

        ORDER_MAP = {
            '-planned_date': 'planned_date DESC',
            'planned_date': 'planned_date ASC',
            '-pending_amount': 'pending_amount DESC',
            'pending_amount': 'pending_amount ASC',
            '-apply_amount': 'apply_amount DESC',
            'apply_amount': 'apply_amount ASC',
            '-paid_amount': 'paid_amount DESC',
            'paid_amount': 'paid_amount ASC',
            '-applicant_name': 'applicant_name DESC',
            'applicant_name': 'applicant_name ASC',
            '-project_name': 'project_name DESC',
            'project_name': 'project_name ASC',
            '-id': 'id DESC',
            'id': 'id ASC',
        }
        order_str = ORDER_MAP.get(ordering, 'planned_date DESC')

        with connection.cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) FROM payment_registrations WHERE {' AND '.join(where)}",
                params
            )
            total = cur.fetchone()[0]

        offset = (page - 1) * page_size
        data_sql = (
            f"SELECT id, applicant_name, invoice_no, description, project_name, "
            f"planned_date, apply_amount, paid_amount, pending_amount, pay_date, "
            f"is_paid, payment_manager, has_invoice, source_sheet, expense_summary, created_at "
            f"FROM payment_registrations "
            f"WHERE {' AND '.join(where)} "
            f"ORDER BY {order_str} "
            f"LIMIT %s OFFSET %s"
        )
        with connection.cursor() as cur:
            cur.execute(data_sql, params + [page_size, offset])
            rows = cur.fetchall()

        results = []
        for r in rows:
            results.append({
                'id': r[0],
                'applicant_name': r[1],
                'invoice_no': r[2],
                'description': r[3],
                'project_name': r[4],
                'planned_date': r[5].isoformat() if r[5] else None,
                'apply_amount': float(r[6]) if r[6] else 0,
                'paid_amount': float(r[7]) if r[7] else 0,
                'pending_amount': float(r[8]) if r[8] else 0,
                'pay_date': r[9].isoformat() if r[9] else None,
                'is_paid': bool(r[10]),
                'payment_manager': r[11],
                'has_invoice': bool(r[12]),
                'source_sheet': r[13],
                'expense_summary': float(r[14]) if r[14] else 0,
                'created_at': r[15].isoformat() if r[15] else None,
                # 衍生字段
                'is_approved': bool(r[2]),  # 有钉钉编号=已审批
                'has_plan': bool(r[5]),       # 有计划日期
            })

        return Response({
            'count': total,
            'page': page,
            'page_size': page_size,
            'results': results
        })

    def post(self, request):
        """新增付款记录"""
        data = request.data
        with connection.cursor() as cur:
            cur.execute(
                """INSERT INTO payment_registrations
                (applicant_name, invoice_no, description, project_name, planned_date,
                 apply_amount, paid_amount, pending_amount, pay_date, is_paid,
                 payment_manager, has_invoice, source_sheet, expense_summary)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                [
                    data.get('applicant_name'), data.get('invoice_no'),
                    data.get('description'), data.get('project_name'),
                    data.get('planned_date') or None,
                    float(data.get('apply_amount') or 0),
                    float(data.get('paid_amount') or 0),
                    float(data.get('pending_amount') or 0),
                    data.get('pay_date') or None,
                    1 if data.get('is_paid') else 0,
                    data.get('payment_manager'),
                    1 if data.get('has_invoice') else 0,
                    data.get('source_sheet', '报销基础统计表'),
                    float(data.get('expense_summary') or 0),
                ]
            )
            new_id = cur.lastrowid
        return Response({'id': new_id, 'created': True}, status=201)

    def put(self, request):
        """更新记录"""
        pid = request.query_params.get('id') or request.data.get('id')
        data = request.data
        with connection.cursor() as cur:
            cur.execute(
                """UPDATE payment_registrations SET
                applicant_name=%s, invoice_no=%s, description=%s, project_name=%s,
                planned_date=%s, apply_amount=%s, paid_amount=%s, pending_amount=%s,
                pay_date=%s, is_paid=%s, payment_manager=%s, has_invoice=%s,
                source_sheet=%s, expense_summary=%s
                WHERE id=%s""",
                [
                    data.get('applicant_name'), data.get('invoice_no'),
                    data.get('description'), data.get('project_name'),
                    data.get('planned_date') or None,
                    float(data.get('apply_amount') or 0),
                    float(data.get('paid_amount') or 0),
                    float(data.get('pending_amount') or 0),
                    data.get('pay_date') or None,
                    1 if data.get('is_paid') else 0,
                    data.get('payment_manager'),
                    1 if data.get('has_invoice') else 0,
                    data.get('source_sheet', '报销基础统计表'),
                    float(data.get('expense_summary') or 0),
                    pid
                ]
            )
        return Response({'id': pid, 'updated': True})

    def delete(self, request):
        """删除记录"""
        pid = request.query_params.get('id')
        if not pid:
            return Response({'error': 'id required'}, status=400)
        with connection.cursor() as cur:
            cur.execute("DELETE FROM payment_registrations WHERE id=%s", [pid])
        return Response({'id': pid, 'deleted': True})


class PaymentRegistrationSummaryView(APIView):
    """付款登记表 - 汇总统计（钉钉已审批口径）"""

    def get(self, request):
        with connection.cursor() as cur:
            # 总览：已审批（有钉钉编号）、已付（有付款日期）
            cur.execute("""
                SELECT
                    COUNT(*) as total_count,
                    SUM(CASE WHEN invoice_no IS NOT NULL AND invoice_no != '' THEN 1 ELSE 0 END) as approved_count,
                    COALESCE(SUM(pending_amount), 0) as total_pending,
                    COALESCE(SUM(paid_amount), 0) as total_paid,
                    COALESCE(SUM(apply_amount), 0) as total_apply,
                    SUM(CASE WHEN is_paid=1 THEN 1 ELSE 0 END) as paid_count,
                    SUM(CASE WHEN is_paid=0 AND (invoice_no IS NOT NULL AND invoice_no != '') THEN 1 ELSE 0 END) as approved_unpaid_count
                FROM payment_registrations
            """)
            row = cur.fetchone()

            # 按项目汇总
            cur.execute("""
                SELECT project_name,
                       COUNT(*) as cnt,
                       COALESCE(SUM(apply_amount), 0) as total_apply,
                       COALESCE(SUM(paid_amount), 0) as total_paid,
                       COALESCE(SUM(pending_amount), 0) as total_pending
                FROM payment_registrations
                WHERE project_name IS NOT NULL
                GROUP BY project_name
                ORDER BY total_pending DESC
                LIMIT 20
            """)
            by_project = [
                {'project_name': r[0], 'count': r[1],
                 'total_apply': float(r[2]), 'total_paid': float(r[3]), 'total_pending': float(r[4])}
                for r in cur.fetchall()
            ]

            # 按付款经理汇总
            cur.execute("""
                SELECT payment_manager,
                       COUNT(*) as cnt,
                       COALESCE(SUM(apply_amount), 0) as total_apply,
                       COALESCE(SUM(paid_amount), 0) as total_paid,
                       COALESCE(SUM(pending_amount), 0) as total_pending
                FROM payment_registrations
                WHERE payment_manager IS NOT NULL AND payment_manager != ''
                GROUP BY payment_manager
                ORDER BY total_pending DESC
            """)
            by_manager = [
                {'payment_manager': r[0], 'count': r[1],
                 'total_apply': float(r[2]), 'total_paid': float(r[3]), 'total_pending': float(r[4])}
                for r in cur.fetchall()
            ]

            # 按月汇总
            cur.execute("""
                SELECT DATE_FORMAT(planned_date, '%%Y-%%m') as m,
                       COUNT(*) as cnt,
                       COALESCE(SUM(apply_amount), 0) as total_apply,
                       COALESCE(SUM(paid_amount), 0) as total_paid,
                       COALESCE(SUM(pending_amount), 0) as total_pending
                FROM payment_registrations
                WHERE planned_date IS NOT NULL
                GROUP BY m
                ORDER BY m DESC
            """)
            by_month = [
                {'month': r[0], 'count': r[1],
                 'total_apply': float(r[2]), 'total_paid': float(r[3]), 'total_pending': float(r[4])}
                for r in cur.fetchall()
            ]

        return Response({
            'summary': {
                'total_count': row[0] or 0,
                'approved_count': row[1] or 0,
                'total_pending': float(row[2]) if row[2] else 0,
                'total_paid': float(row[3]) if row[3] else 0,
                'total_apply': float(row[4]) if row[4] else 0,
                'paid_count': row[5] or 0,
                'approved_unpaid_count': row[6] or 0,
            },
            'by_project': by_project,
            'by_manager': by_manager,
            'by_month': by_month,
        })
