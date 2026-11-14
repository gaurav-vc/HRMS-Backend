tarimport json
import urllib.request
import urllib.error

BASE = 'http://127.0.0.1:8000'

def make_request(url, method='GET', data=None, headers=None):
    if headers is None:
        headers = {}
    req_data = None
    if data is not None:
        req_data = json.dumps(data).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    
    req = urllib.request.Request(url, data=req_data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            content = resp.read().decode('utf-8')
            return resp.status, json.loads(content) if content else {}
    except urllib.error.HTTPError as e:
        err_content = e.read().decode('utf-8')
        try:
            return e.code, json.loads(err_content)
        except Exception:
            return e.code, err_content
    except Exception as e:
        return 0, str(e)

def test_user(username, password):
    print(f'==============================')
    print(f'Testing User: {username}')
    print(f'==============================')
    status, res = make_request(f'{BASE}/api/auth/token/', method='POST', data={'username': username, 'password': password})
    if status != 200:
        print(f'Failed to get token: {status} {res}')
        return
    token = res.get('access')
    headers = {'Authorization': f'Bearer {token}'}
    
    # Check user profile
    status, me = make_request(f'{BASE}/api/auth/me/', headers=headers)
    if status == 200:
        print(f'Profile 200 OK: username={me.get("username")}, role={me.get("role")}, is_superuser={me.get("is_superuser")}')
    else:
        print(f'Profile error: {status} {me}')

    # Check various modules
    endpoints = [
        '/api/employees/',
        '/api/attendance/',
        '/api/leaves/',
        '/api/payroll/runs/',
        '/api/payroll/slips/',
        '/api/payroll/form16/'
    ]
    for ep in endpoints:
        ep_status, data = make_request(f'{BASE}{ep}', headers=headers)
        if ep_status == 200:
            count = len(data) if isinstance(data, list) else (data.get('count') if isinstance(data, dict) else 'ok')
            print(f'  {ep:<25} -> 200 OK (count: {count})')
        else:
            err_msg = str(data)[:80] if data else 'Unknown'
            print(f'  {ep:<25} -> {ep_status} ({err_msg})')

for u in ['admin_user', 'Admin', 'siteadmin', 'employee']:
    test_user(u, '123')
