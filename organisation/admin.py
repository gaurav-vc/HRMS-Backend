from django.contrib import admin
from .models import Entity, Branch, Site, Department, Designation

admin.site.register(Entity)
admin.site.register(Branch)
admin.site.register(Site)
admin.site.register(Department)
admin.site.register(Designation)
