from django.db import models
from django.db.models import Sum, Count, F
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import viewsets
from .models import Project
from .serializers import ProjectSerializer


class ProjectViewSet(viewsets.ModelViewSet):
    """项目管理 CRUD"""
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        keyword = self.request.query_params.get('search', '')
        manager = self.request.query_params.get('manager_name', '')
        project_name = self.request.query_params.get('project_name', '')
        ordering = self.request.query_params.get('ordering', '').strip()

        if keyword:
            from django.db.models import Q
            qs = qs.filter(
                Q(project_name__icontains=keyword) |
                Q(project_code__icontains=keyword) |
                Q(customer_name__icontains=keyword)
            )
        if manager:
            qs = qs.filter(manager_name=manager)
        if project_name:
            qs = qs.filter(project_name=project_name)

        if ordering:
            field_map = {
                'project_name': 'project_name', '-project_name': '-project_name',
                'manager_name': 'manager_name', '-manager_name': '-manager_name',
                'contract_amount': 'contract_amount', '-contract_amount': '-contract_amount',
                'created_at': 'created_at', '-created_at': '-created_at',
                'business_model': 'business_model', '-business_model': '-business_model',
                'department': 'department', '-department': '-department',
                'id': 'id', '-id': '-id',
            }
            order_field = field_map.get(ordering, '-created_at')
            qs = qs.order_by(order_field)
        else:
            qs = qs.order_by('-created_at')

        return qs

    def perform_create(self, serializer):
        instance = serializer.save()
        if not instance.project_code:
            import uuid
            code = 'PRJ' + uuid.uuid4().hex[:8].upper()
            Project.objects.filter(pk=instance.pk).update(project_code=code)

    def update(self, request, *args, **kwargs):
        data = request.data.copy()
        data.pop('status', None)
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        data = request.data.copy()
        data.pop('status', None)
        return super().partial_update(request, *args, **kwargs)


class ProjectSummaryView(APIView):
    """项目统计（含Dashboard所需的KPI）"""

    def get(self, request):
        from django.db import connection

        month = request.query_params.get('month', '')
        year = request.query_params.get('year', '')

        with connection.cursor() as cur:
            # 总项目数、经理数
            cur.execute('SELECT COUNT(*), COUNT(DISTINCT manager_name) FROM projects')
            row = cur.fetchone()
            total_projects = row[0] or 0
            total_managers = row[1] or 0

            # 未回款总额（来自unpaid_records）
            cur.execute("SELECT COALESCE(SUM(unpaid_amount),0) FROM unpaid_records")
            total_unpaid = float(cur.fetchone()[0] or 0)

            # 逾期总额（来自unpaid_records）
            cur.execute("SELECT COALESCE(SUM(abnormal_amount),0) FROM unpaid_records WHERE status = 'abnormal'")
            abnormal_total = float(cur.fetchone()[0] or 0)

            # 本月新增项目
            new_this_month = 0
            if month:
                cur.execute("SELECT COUNT(*) FROM projects WHERE DATE_FORMAT(created_at, '%%Y-%%m') = %s", [month])
                new_this_month = cur.fetchone()[0] or 0
            elif year:
                cur.execute("SELECT COUNT(*) FROM projects WHERE DATE_FORMAT(created_at, '%%Y') = %s", [year])
                new_this_month = cur.fetchone()[0] or 0

            # 按业务模式聚合
            cur.execute("""
                SELECT business_model,
                       COUNT(*) as cnt,
                       COALESCE(SUM(contract_amount), 0) as total_amount
                FROM projects
                WHERE business_model IS NOT NULL AND business_model != ''
                GROUP BY business_model
                ORDER BY cnt DESC
            """)
            by_business = []
            for r in cur.fetchall():
                by_business.append({
                    'business_model': r[0] or '(未填)',
                    'count': r[1],
                    'total_amount': float(r[2])
                })

            # 按部门聚合
            cur.execute("""
                SELECT department,
                       COUNT(*) as cnt,
                       COALESCE(SUM(contract_amount), 0) as total_amount
                FROM projects
                WHERE department IS NOT NULL AND department != ''
                GROUP BY department
                ORDER BY cnt DESC
            """)
            by_department = []
            for r in cur.fetchall():
                by_department.append({
                    'department': r[0] or '(未填)',
                    'count': r[1],
                    'total_amount': float(r[2])
                })

            # 按经理聚合
            cur.execute("""
                SELECT manager_name,
                       COUNT(*) as cnt,
                       COALESCE(SUM(contract_amount), 0) as total_amount
                FROM projects
                WHERE manager_name IS NOT NULL AND manager_name != ''
                GROUP BY manager_name
                ORDER BY cnt DESC
            """)
            by_manager = []
            for r in cur.fetchall():
                by_manager.append({
                    'manager_name': r[0] or '(未填)',
                    'count': r[1],
                    'total_amount': float(r[2])
                })

        return Response({
            'total_projects': total_projects,
            'manager_count': total_managers,
            'total_unpaid': total_unpaid,
            'abnormal_total': abnormal_total,
            'new_this_month': new_this_month,
            'by_business': by_business,
            'by_department': by_department,
            'by_manager': by_manager,
        })


class UnpaidRecordsView(APIView):
    """未回款记录查询"""

    def get(self, request):
        from django.db import connection

        project_name = request.query_params.get('project_name', '').strip()
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 50))

        where = ['1=1']
        params = []
        if project_name:
            where.append('project_name = %s')
            params.append(project_name)

        with connection.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM unpaid_records WHERE {' AND '.join(where)}", params)
            total = cur.fetchone()[0]

        offset = (page - 1) * page_size
        with connection.cursor() as cur:
            cur.execute(
                f"SELECT id, project_id, project_name, manager_name, abnormal_amount, "
                f"received_amount, unpaid_amount, days_overdue, status, record_date, created_at "
                f"FROM unpaid_records WHERE {' AND '.join(where)} "
                f"ORDER BY days_overdue DESC LIMIT %s OFFSET %s",
                params + [page_size, offset]
            )
            rows = cur.fetchall()

        results = []
        for r in rows:
            results.append({
                'id': r[0], 'project_id': r[1], 'project_name': r[2],
                'manager_name': r[3], 'abnormal_amount': float(r[4]) if r[4] else 0,
                'received_amount': float(r[5]) if r[5] else 0,
                'unpaid_amount': float(r[6]) if r[6] else 0,
                'days_overdue': r[7] or 0,
                'status': r[8] or 'normal',
                'record_date': r[9].isoformat() if r[9] else None,
                'created_at': r[10].isoformat() if r[10] else None,
            })

        return Response({'count': total, 'results': results})
