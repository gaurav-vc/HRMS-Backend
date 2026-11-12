from rest_framework import serializers
from .models import Entity, Branch, Site, Department, Designation, Role, AttendancePolicy, PunctualitySlab, PunctualityPenaltyLog


class EntitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Entity
        fields = '__all__'

class BranchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Branch
        fields = '__all__'

class SiteSerializer(serializers.ModelSerializer):
    organization_name = serializers.CharField(source='organization.name', read_only=True)
    parent_site_name = serializers.CharField(source='parent_site.name', read_only=True)
    users_count = serializers.SerializerMethodField()
    entity = serializers.SerializerMethodField()

    class Meta:
        model = Site
        fields = '__all__'

    def get_users_count(self, obj):
        return obj.employees.count() if hasattr(obj, 'employees') else 0

    def get_entity(self, obj):
        return obj.branch.entity_id if obj.branch else None

class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = '__all__'

class DesignationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Designation
        fields = '__all__'

class RoleSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source='department.name', read_only=True)
    reporting_to_name = serializers.SerializerMethodField()
    
    class Meta:
        model = Role
        fields = '__all__'

    def get_reporting_to_name(self, obj):
        if obj.reporting_to:
            return obj.reporting_to.name
        return None

class PunctualitySlabSerializer(serializers.ModelSerializer):
    applicable_designation_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Designation.objects.all(), source='applicable_designations', required=False
    )
    applicable_designations_details = serializers.SerializerMethodField()
    applicable_role_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Role.objects.all(), source='applicable_roles', required=False
    )
    applicable_roles_details = serializers.SerializerMethodField()

    class Meta:
        model = PunctualitySlab
        fields = [
            'id', 'policy', 'name', 'comparison_type', 'minutes_threshold',
            'deduction_type', 'deduction_value', 'order',
            'applicable_designation_ids', 'applicable_designations_details',
            'applicable_role_ids', 'applicable_roles_details'
        ]

    def get_applicable_designations_details(self, obj):
        return [{'id': d.id, 'title': d.title} for d in obj.applicable_designations.all()]

    def get_applicable_roles_details(self, obj):
        return [{'id': r.id, 'name': r.name} for r in obj.applicable_roles.all()]


class AttendancePolicySerializer(serializers.ModelSerializer):
    punctuality_slabs = PunctualitySlabSerializer(many=True, read_only=True)

    class Meta:
        model = AttendancePolicy
        fields = '__all__'
        extra_kwargs = {
            'site': {'validators': []},
            'organization': {'validators': []},
            'employee': {'validators': []},
        }

    def to_internal_value(self, data):
        data = data.copy() if hasattr(data, 'copy') else dict(data)
        if 'wfhEmployees' in data and 'wfh_employees' not in data:
            data['wfh_employees'] = data.get('wfhEmployees')
        return super().to_internal_value(data)

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        wfh_ids = list(instance.wfh_employees.values_list('id', flat=True))
        ret['wfh_employees'] = wfh_ids
        ret['wfhEmployees'] = wfh_ids
        return ret
