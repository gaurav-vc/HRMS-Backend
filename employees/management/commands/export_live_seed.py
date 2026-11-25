import os
import sys
from django.core.management.base import BaseCommand
import export_live_seed

class Command(BaseCommand):
    help = 'Safely export live HRMS database to a sanitized seed file for dev/QA'

    def add_arguments(self, parser):
        parser.add_argument(
            "--output", 
            default="hrms_live_seed.json", 
            help="Output file path (default: hrms_live_seed.json)"
        )
        parser.add_argument(
            "--compress", 
            action="store_true", 
            help="Gzip compress output file (.json.gz)"
        )
        parser.add_argument(
            "--include-punches", 
            action="store_true", 
            help="Include daily attendance and biometric punches"
        )

    def handle(self, *args, **options):
        export_live_seed.export_live_data(
            output_path=options["output"],
            compress=options["compress"],
            include_punches=options["include_punches"]
        )
