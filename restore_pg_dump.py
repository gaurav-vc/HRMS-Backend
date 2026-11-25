import os
import sys
import subprocess
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

PSQL_BIN = r"C:\Program Files\PostgreSQL\18\bin\psql.exe"
PG_HOST = "127.0.0.1"
PG_PORT = 5432
PG_ADMIN_USER = "postgres"
PG_ADMIN_PASS = "kash"

DB_NAME = "hrms_db"
DB_USER = "hrms_user"
DB_PASS = "hrms_password"
DUMP_FILE = r"c:\Hrms\HRMS-Backend\hrms_db_dump.sql"

def main():
    print("=" * 70)
    print("RESTORING POSTGRESQL DATABASE FROM hrms_db_dump.sql")
    print("=" * 70)

    # 1. Connect to default postgres DB
    print("[1/5] Connecting to PostgreSQL server...")
    conn = psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        user=PG_ADMIN_USER,
        password=PG_ADMIN_PASS,
        dbname="postgres"
    )
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cursor = conn.cursor()

    # 2. Ensure role hrms_user exists
    print("[2/5] Ensuring role 'hrms_user' exists...")
    cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (DB_USER,))
    if not cursor.fetchone():
        cursor.execute(f"CREATE ROLE {DB_USER} WITH LOGIN SUPERUSER PASSWORD '{DB_PASS}';")
        print(f"  -> Created role '{DB_USER}' with superuser privileges.")
    else:
        cursor.execute(f"ALTER ROLE {DB_USER} WITH LOGIN SUPERUSER PASSWORD '{DB_PASS}';")
        print(f"  -> Updated role '{DB_USER}'.")

    # 3. Terminate connections and recreate hrms_db
    print(f"[3/5] Recreating clean database '{DB_NAME}'...")
    cursor.execute(f"""
        SELECT pg_terminate_backend(pid) 
        FROM pg_stat_activity 
        WHERE datname = '{DB_NAME}' AND pid != pg_backend_pid();
    """)
    cursor.execute(f"DROP DATABASE IF EXISTS {DB_NAME};")
    cursor.execute(f"CREATE DATABASE {DB_NAME} OWNER {DB_USER} ENCODING 'UTF8';")
    print(f"  -> Database '{DB_NAME}' created cleanly.")
    cursor.close()
    conn.close()

    # 4. Import the dump file using psql
    print(f"[4/5] Importing SQL dump '{DUMP_FILE}' into '{DB_NAME}'...")
    env = os.environ.copy()
    env["PGPASSWORD"] = PG_ADMIN_PASS
    
    cmd = [
        PSQL_BIN,
        "-h", PG_HOST,
        "-p", str(PG_PORT),
        "-U", PG_ADMIN_USER,
        "-d", DB_NAME,
        "-f", DUMP_FILE,
        "-v", "ON_ERROR_STOP=0"
    ]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    print(f"  -> psql finished with return code {proc.returncode}.")
    if proc.stderr:
        err_lines = [l for l in proc.stderr.splitlines() if "ERROR" in l]
        if err_lines:
            print(f"  -> Encountered {len(err_lines)} error lines during SQL import (e.g. {err_lines[:3]}).")

    # 5. Connect to hrms_db and reset passwords to '123'
    print("[5/5] Normalizing all user account passwords to '123'...")
    # Django PBKDF2 hash for password '123'
    # We can use Django make_password
    sys.path.insert(0, r"c:\Hrms\HRMS-Backend")
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
    import django
    # Temporarily setup django to use make_password
    from django.contrib.auth.hashers import make_password
    pwd_123_hash = make_password("123")

    conn_db = psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        user=PG_ADMIN_USER,
        password=PG_ADMIN_PASS,
        dbname=DB_NAME
    )
    conn_db.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur_db = conn_db.cursor()

    cur_db.execute("SELECT COUNT(*) FROM auth_user;")
    user_count = cur_db.fetchone()[0]

    cur_db.execute("UPDATE auth_user SET password = %s;", (pwd_123_hash,))
    print(f"  -> Successfully updated passwords for {user_count} users to '123'!")

    # Check some key statistics
    cur_db.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;")
    tables = [t[0] for t in cur_db.fetchall()]
    print(f"  -> Total tables restored: {len(tables)}")
    print("  -> Tables present:", tables)

    cur_db.execute("SELECT COUNT(*) FROM auth_user;")
    print("  -> auth_user count:", cur_db.fetchone()[0])

    # List sample users
    cur_db.execute("SELECT username, email, is_staff, is_superuser FROM auth_user ORDER BY id ASC LIMIT 5;")
    sample_users = cur_db.fetchall()
    print("  -> Sample users in restored DB:")
    for u in sample_users:
        print(f"     - {u[0]} ({u[1]}) [Staff: {u[2]}, Superuser: {u[3]}]")

    cur_db.close()
    conn_db.close()

    print("=" * 70)
    print("DATABASE RESTORE COMPLETED SUCCESSFULLY")
    print("=" * 70)

if __name__ == "__main__":
    main()
