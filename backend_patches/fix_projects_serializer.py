from rest_framework import serializers
from .models import Project


class ProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = ['id', 'project_name', 'project_code', 'customer_name',
                  'manager_name', 'contract_amount',
                  'business_model', 'department',
                  'sales_contact', 'shared_type', 'settlement_cycle',
                  'created_at']
        read_only_fields = ['id', 'created_at']
