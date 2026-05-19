from rest_framework import viewsets
from .models import Payable
from .serializers import PayableSerializer


class PayableViewSet(viewsets.ModelViewSet):
    """应付账款（未回款记录）CRUD - 对接 unpaid_records 表"""
    queryset = Payable.objects.all()
    serializer_class = PayableSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        keyword = self.request.query_params.get('search', '')
        project_name = self.request.query_params.get('project_name', '')
        project_id = self.request.query_params.get('project_id')
        status_filter = self.request.query_params.get('status', '')
        manager_name = self.request.query_params.get('manager_name', '')

        if keyword:
            qs = qs.filter(project_name__icontains=keyword) | qs.filter(manager_name__icontains=keyword)
        if project_name:
            qs = qs.filter(project_name=project_name)
        if project_id:
            qs = qs.filter(project_id=project_id)
        if status_filter:
            qs = qs.filter(status=status_filter)
        if manager_name:
            qs = qs.filter(manager_name=manager_name)
        return qs
