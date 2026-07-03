from rest_framework import viewsets
from .models import Entity, Branch, Site, Department, Designation, Role, AttendancePolicy
from .serializers import (
    EntitySerializer, BranchSerializer, SiteSerializer,
    DepartmentSerializer, DesignationSerializer, RoleSerializer,
    AttendancePolicySerializer
)

class EntityViewSet(viewsets.ModelViewSet):
    queryset = Entity.objects.all()
    serializer_class = EntitySerializer

class AttendancePolicyViewSet(viewsets.ModelViewSet):
    queryset = AttendancePolicy.objects.all()
    serializer_class = AttendancePolicySerializer
    filterset_fields = ['site', 'organization', 'employee']

class BranchViewSet(viewsets.ModelViewSet):
    queryset = Branch.objects.all()
    serializer_class = BranchSerializer

class SiteViewSet(viewsets.ModelViewSet):
    queryset = Site.objects.all()
    serializer_class = SiteSerializer

class DepartmentViewSet(viewsets.ModelViewSet):
    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer

class DesignationViewSet(viewsets.ModelViewSet):
    queryset = Designation.objects.all()
    serializer_class = DesignationSerializer

from org_engine.models import OrganizationNode
from org_engine.engine import HierarchyEngine

class RoleViewSet(viewsets.ModelViewSet):
    queryset = Role.objects.all()
    serializer_class = RoleSerializer

    def perform_create(self, serializer):
        role = serializer.save()
        try:
            from org_engine.models import OrganizationNode, OrganizationNodeType
            role_type, _ = OrganizationNodeType.objects.get_or_create(name='Role')
            
            parent_node = None
            if role.reporting_to:
                parent_node = OrganizationNode.objects.filter(name=role.reporting_to.name, node_type__name='Role').first()
            elif role.department:
                parent_node = OrganizationNode.objects.filter(name=role.department.name, node_type__name='Department').first()
                
            if not parent_node:
                parent_node = OrganizationNode.objects.filter(
                    parent__isnull=True
                ).exclude(node_type__name__in=['Role', 'Employee', 'Department']).first()
                
            OrganizationNode.objects.create(
                name=role.name,
                node_type=role_type,
                parent=parent_node
            )
        except Exception as e:
            print(f"Failed to create org engine node for role: {e}")

    def perform_update(self, serializer):
        old_reporting_to = serializer.instance.reporting_to
        old_name = serializer.instance.name
        role = serializer.save()

        # Update the Organization Graph
        try:
            # Attempt to find the corresponding OrganizationNode (matching by name since legacy_role_id may be null)
            role_node = OrganizationNode.objects.filter(name=old_name, node_type__name='Role').first()
            
            if role_node:
                # If name changed, update it
                if old_name != role.name:
                    role_node.name = role.name
                    role_node.save(update_fields=['name'])

                # If reporting structure changed, move the node
                if role.reporting_to != old_reporting_to:
                    new_parent_node = None
                    if role.reporting_to:
                        new_parent_node = OrganizationNode.objects.filter(name=role.reporting_to.name, node_type__name='Role').first()
                    elif role.department:
                        new_parent_node = OrganizationNode.objects.filter(name=role.department.name, node_type__name='Department').first()
                    
                    if new_parent_node and role_node.parent_id != new_parent_node.id:
                        HierarchyEngine.move_node(role_node, new_parent_node)
        except Exception as e:
            print(f"Failed to sync org engine graph: {e}")

    def perform_destroy(self, instance):
        try:
            # Sync deletion to Org Engine
            role_node = OrganizationNode.objects.filter(name=instance.name, node_type__name='Role').first()
            if role_node:
                # If there are children, you might want to handle it properly, but cascading is fine for now
                role_node.delete()
        except Exception as e:
            print(f"Failed to delete org engine graph node: {e}")
            
        instance.delete()
