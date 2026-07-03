from django.db import models
from django.db import transaction
from django.core.exceptions import ValidationError

class OrganizationNodeType(models.Model):
    """
    Defines the completely dynamic node types.
    E.g. Group, Business Unit, Legal Entity, Region, Department, Role, Position, Employee.
    No hardcoded hierarchy levels.
    """
    name = models.CharField(max_length=100)
    level_order = models.IntegerField(default=0)
    description = models.TextField(blank=True, null=True)
    
    class Meta:
        ordering = ['level_order']
    
    def __str__(self):
        return self.name

class OrganizationNode(models.Model):
    """
    Single Source of Truth for every structural object in the organization.
    Uses Materialized Path for sub-second recursive operations.
    """
    tenant_id = models.IntegerField(default=1, db_index=True)
    
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    node_type = models.ForeignKey(OrganizationNodeType, on_delete=models.PROTECT, related_name='nodes')
    
    # Adjacency List for standard tree building
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='children')
    
    # Materialized Path (e.g. "000001.000005.000123")
    path = models.CharField(max_length=255, db_index=True, blank=True)
    depth = models.IntegerField(default=0)
    
    # Effective Dating
    effective_from = models.DateTimeField(auto_now_add=True)
    effective_to = models.DateTimeField(null=True, blank=True)
    
    status = models.CharField(max_length=50, default='Active') # Active, Archived, SoftDeleted
    
    # Legacy bindings (to be migrated/deprecated later)
    legacy_entity_id = models.IntegerField(null=True, blank=True)
    legacy_department_id = models.IntegerField(null=True, blank=True)
    legacy_project_id = models.IntegerField(null=True, blank=True)
    legacy_role_id = models.IntegerField(null=True, blank=True)
    legacy_employee_id = models.IntegerField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        
        # If no path exists, we must save first to get an ID (if not provided).
        if is_new and not self.pk:
            super().save(*args, **kwargs)
            is_new = False
            # Remove force_insert so the second save does an UPDATE
            kwargs.pop('force_insert', None)
            kwargs['force_update'] = True
            
        self._generate_path()
        super().save(*args, **kwargs)

    def _generate_path(self):
        padded_id = f"{self.id:06d}"
        if self.parent:
            self.path = f"{self.parent.path}.{padded_id}"
            self.depth = self.parent.depth + 1
        else:
            self.path = padded_id
            self.depth = 0

    def get_ancestors(self):
        """Returns all ancestors ordered from root to immediate parent."""
        if not self.path:
            return OrganizationNode.objects.none()
        path_parts = self.path.split('.')[:-1]
        if not path_parts:
            return OrganizationNode.objects.none()
        
        # Reconstruct paths for IN clause
        paths_to_query = []
        current = ""
        for part in path_parts:
            current = f"{current}.{part}" if current else part
            paths_to_query.append(current)
            
        return OrganizationNode.objects.filter(path__in=paths_to_query).order_by('depth')

    def get_descendants(self, include_self=False):
        """Returns all descendants in the entire subtree."""
        qs = OrganizationNode.objects.filter(path__startswith=f"{self.path}.")
        if include_self:
            qs = OrganizationNode.objects.filter(models.Q(path__startswith=f"{self.path}.") | models.Q(id=self.id))
        return qs.order_by('path')

    def __str__(self):
        return f"{self.name} ({self.node_type.name})"


class OrganizationAuditLog(models.Model):
    """
    Immutable audit logs containing before-state, after-state, affected records, rollback metadata.
    """
    node = models.ForeignKey(OrganizationNode, on_delete=models.CASCADE, related_name='audit_logs')
    action = models.CharField(max_length=100) # CREATE, MOVE, CLONE, ARCHIVE, RESTORE
    
    # State tracking
    old_parent = models.ForeignKey(OrganizationNode, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    new_parent = models.ForeignKey(OrganizationNode, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    
    before_state = models.JSONField(null=True, blank=True)
    after_state = models.JSONField(null=True, blank=True)
    
    performed_by_name = models.CharField(max_length=255, default='System')
    timestamp = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    
    # Hash chaining for immutability
    previous_hash = models.CharField(max_length=64, blank=True, null=True)
    hash = models.CharField(max_length=64, blank=True, null=True)

    def __str__(self):
        return f"{self.action} on {self.node.name} at {self.timestamp}"


class NodeRelationship(models.Model):
    """
    Supports Matrix Reporting and dynamic secondary relationships.
    E.g. Administrative, Functional, Project, Matrix.
    """
    RELATIONSHIP_TYPES = [
        ('Administrative', 'Administrative'), # Typically handled by the primary 'parent' field, but can be explicit here
        ('Functional', 'Functional'),
        ('Project', 'Project'),
        ('HR', 'HR'),
        ('Matrix', 'Matrix'),
        ('Temporary', 'Temporary'),
        ('Delegate', 'Delegate'),
    ]
    
    source_node = models.ForeignKey(OrganizationNode, on_delete=models.CASCADE, related_name='outgoing_relationships')
    target_node = models.ForeignKey(OrganizationNode, on_delete=models.CASCADE, related_name='incoming_relationships')
    relationship_type = models.CharField(max_length=50, choices=RELATIONSHIP_TYPES)
    
    effective_from = models.DateTimeField(auto_now_add=True)
    effective_to = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=50, default='Active')

    class Meta:
        unique_together = ('source_node', 'target_node', 'relationship_type', 'effective_from')

    def __str__(self):
        return f"{self.source_node.name} -> {self.relationship_type} -> {self.target_node.name}"


class HierarchyHistory(models.Model):
    """
    Enterprise History Engine logging mechanism.
    Tracks structural movement over time for accurate historical point-in-time querying.
    """
    node = models.ForeignKey(OrganizationNode, on_delete=models.CASCADE, related_name='history_logs')
    parent_at_time = models.ForeignKey(OrganizationNode, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    path_at_time = models.CharField(max_length=255)
    
    effective_from = models.DateTimeField()
    effective_to = models.DateTimeField(null=True, blank=True)
    
    recorded_at = models.DateTimeField(auto_now_add=True)
    reason = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        ordering = ['-effective_from']

    def __str__(self):
        return f"History for {self.node.name} ({self.effective_from} to {self.effective_to or 'Present'})"

