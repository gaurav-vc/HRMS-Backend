import os
import sys
from django.core.management.base import BaseCommand
import seed_live_data

class Command(BaseCommand):
    help = 'Seeds entire HRMS database from a live server REST API, a JSON dump fixture, or the built-in Lotus baseline'

    def add_arguments(self, parser):
        parser.add_argument(
            "--mode", 
            choices=["api", "file", "lotus"], 
            default=None,
            help="Sync mode: 'api' (pull from live URL), 'file' (from JSON dump), or 'lotus' (local baseline)"
        )
        parser.add_argument(
            "--url", 
            default="https://hrms.lotusdevelopers.com",
            help="Live server base URL (default: https://hrms.lotusdevelopers.com)"
        )
        parser.add_argument("--email", default=None, help="Live admin login email")
        parser.add_argument("--password", default=None, help="Live admin login password")
        parser.add_argument("--token", default=None, help="Direct JWT Bearer token")
        parser.add_argument("--file", default="data.json", help="Path to JSON dump file (for --mode file)")
        parser.add_argument(
            "--default-password", 
            default=seed_live_data.DEFAULT_PASSWORD, 
            help=f"Password to set for all local accounts (default: {seed_live_data.DEFAULT_PASSWORD})"
        )
        parser.add_argument(
            "--insecure", 
            action="store_true", 
            help="Bypass SSL certificate checks for staging/self-signed domains"
        )

    def handle(self, *args, **options):
        mode = options.get("mode")
        if not mode:
            if options.get("token") or (options.get("email") and options.get("password")):
                mode = "api"
            elif os.path.exists(options.get("file", "")) and options.get("file") != "data.json":
                mode = "file"
            else:
                mode = "lotus"

        self.stdout.write(self.style.SUCCESS("=" * 70))
        self.stdout.write(self.style.SUCCESS(f"HRMS LIVE DATA SEEDING (DJANGO MANAGEMENT COMMAND)"))
        self.stdout.write(self.style.SUCCESS(f"Mode: {mode.upper()} | Target Password: {options['default_password']}"))
        self.stdout.write(self.style.SUCCESS("=" * 70))

        if mode == "api":
            seed_live_data.sync_from_live_api(
                base_url=options["url"],
                email=options.get("email"),
                password=options.get("password"),
                token=options.get("token"),
                default_pwd=options["default_password"],
                insecure=options.get("insecure", False)
            )
        elif mode == "file":
            seed_live_data.sync_from_dump_file(options["file"], default_pwd=options["default_password"])
        elif mode == "lotus":
            seed_live_data.sync_lotus_baseline(default_pwd=options["default_password"])

        self.stdout.write(self.style.SUCCESS("\n[+] Seeding command completed successfully!"))
