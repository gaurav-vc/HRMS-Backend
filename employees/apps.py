from django.apps import AppConfig


class EmployeesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'employees'

    def ready(self):
        import os
        # Prevent running twice in dev mode with auto-reloader
        if os.environ.get('RUN_MAIN', None) != 'true':
            return
            
        from .utils import trigger_birthday_emails
        import threading
        import time
        from datetime import datetime, timedelta

        def run_daily_task():
            while True:
                now = datetime.now()
                # Run everyday at 9:00 AM
                target_time = now.replace(hour=9, minute=0, second=0, microsecond=0)
                
                # If it's past 9 AM, schedule for tomorrow
                if now > target_time:
                    target_time += timedelta(days=1)
                
                sleep_seconds = (target_time - now).total_seconds()
                
                # Sleep until 9 AM
                time.sleep(sleep_seconds)
                
                try:
                    trigger_birthday_emails()
                except Exception as e:
                    print(f"Error sending birthday emails: {e}")

        # Start background thread
        thread = threading.Thread(target=run_daily_task, daemon=True)
        thread.start()
