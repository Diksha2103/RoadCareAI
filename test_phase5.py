"""
RoadCare AI - End-to-End Test Suite

Run the app first (python app.py), then in another terminal:
    python tests/test_phase5.py

Admin credentials are read from ADMIN_USERNAME / ADMIN_PASSWORD
(environment variables or the .env file in the project root).
Optional: ROADCARE_BASE_URL (default http://127.0.0.1:5000).

Tests:
  1. Citizen Registration            14. Admin Search by Complaint ID
  2. Citizen Login                   15. Admin View Complaint Detail
  3. Complaint Submission (photo+GPS) 16. Admin Verification
  4. AI Prediction Display           17. Admin Department Assignment
  5. Citizen Track Page              18. Admin Status Update
  6. Citizen My Complaints           19. Admin Remarks Update
  7. Admin Login (invalid)           20. Admin Repair Update (photo+date)
  8. Admin Login (valid)             21. Citizen Sees Repair Update
  9. Admin Dashboard                 22. Admin Reject & Close
 10. Admin Complaints List           23. Admin Map View
 11. Filter by Severity              24. Public Complaint API
 12. Filter by Damage Type           25. Admin Statistics API
 13. Filter by Status
"""

import http.cookiejar
import json
import os
import random
import re
import string
import struct
import sys
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import date

sys.stdout.reconfigure(encoding='utf-8')

# ─── Configuration ────────────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, '.env'))
except ImportError:
    pass

BASE = os.environ.get('ROADCARE_BASE_URL', 'http://127.0.0.1:5000')
ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD')
if not ADMIN_PASSWORD:
    print("ADMIN_PASSWORD is not set. Put it in .env or the environment before running the tests.")
    sys.exit(2)


# ─── Helpers ──────────────────────────────────────────────────────────────────
def make_png():
    """Build a valid 1x1 PNG in memory (no external files needed)."""
    def chunk(tag, data):
        body = tag + data
        return struct.pack('>I', len(data)) + body + struct.pack('>I', zlib.crc32(body) & 0xffffffff)
    ihdr = struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0)
    idat = zlib.compress(b'\x00\xff\x00\x00\xff')
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr) + chunk(b'IDAT', idat) + chunk(b'IEND', b'')


TINY_PNG = make_png()


def encode_multipart_formdata(fields, files):
    boundary = '----RoadCareBoundary' + ''.join(random.choices(string.ascii_letters + string.digits, k=16))
    lines = []
    for key, value in fields.items():
        lines += [f'--{boundary}'.encode(),
                  f'Content-Disposition: form-data; name="{key}"'.encode(),
                  b'', str(value).encode('utf-8')]
    for key, filename, data, content_type in files:
        lines += [f'--{boundary}'.encode(),
                  f'Content-Disposition: form-data; name="{key}"; filename="{filename}"'.encode(),
                  f'Content-Type: {content_type}'.encode(),
                  b'', data if isinstance(data, bytes) else data.encode()]
    lines += [f'--{boundary}--'.encode(), b'']
    return f'multipart/form-data; boundary={boundary}', b'\r\n'.join(lines)


admin_opener = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
citizen_opener = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def req(opener, url, data=None, headers=None, method='GET'):
    headers = headers or {}
    if data is not None and isinstance(data, dict):
        data = urllib.parse.urlencode(data).encode('utf-8')
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        response = opener.open(request)
        return response.status, response.url, response.read().decode('utf-8', errors='replace')
    except urllib.error.HTTPError as e:
        return e.code, url, e.read().decode('utf-8', errors='replace') if e.fp else ''


results = []


def run_test(name, condition, detail=""):
    results.append((name, condition))
    print(f"[{'PASS' if condition else 'FAIL'}] {name} {('- ' + detail) if detail else ''}")
    return condition


def submit_complaint(opener, address):
    fields = {
        'address': address,
        'landmark': 'Opposite Central Mall',
        'damage_type': 'Pothole',
        'severity': 'High',
        'description': 'Large pothole causing vehicle slowdowns and safety hazards.',
        'latitude': '12.9716',
        'longitude': '77.5946',
    }
    ctype, body = encode_multipart_formdata(fields, [('image', 'pothole_test.png', TINY_PNG, 'image/png')])
    st, url, resp = req(opener, f"{BASE}/report", data=body, headers={'Content-Type': ctype}, method='POST')
    cid = url.split('complaint_id=')[-1].split('&')[0] if 'complaint_id=' in url else ""
    return st, cid, resp


def find_pk(complaint_id):
    """Look up a complaint's database id through the admin list page."""
    _, _, page = req(admin_opener, f"{BASE}/admin/complaints?search_id={complaint_id}")
    match = re.search(r'/admin/complaints/(\d+)', page)
    return match.group(1) if match else None


print("=" * 65)
print("ROADCARE AI - END-TO-END TEST SUITE")
print("=" * 65)

# 1. Citizen Registration
random_user = "user_" + "".join(random.choices(string.ascii_lowercase, k=5))
citizen_password = "Pw!" + "".join(random.choices(string.ascii_letters + string.digits, k=12))
st, url, _ = req(citizen_opener, f"{BASE}/register", {
    'username': random_user, 'email': f"{random_user}@example.com",
    'password': citizen_password, 'full_name': 'Test Citizen', 'phone': '0000000000'
}, method='POST')
run_test("Citizen Registration", st == 200 and 'login' in url, f"Registered as {random_user}")

# 2. Citizen Login
st, url, _ = req(citizen_opener, f"{BASE}/login",
                 {'username': random_user, 'password': citizen_password}, method='POST')
run_test("Citizen Login", st == 200 and url.rstrip('/') == BASE, f"Logged in as {random_user}")

# 3. Complaint Submission
st, created_complaint_id, resp_body = submit_complaint(citizen_opener, 'MG Road, near Metro Pillar 142, Bengaluru')
run_test("Citizen Complaint Submission (with image & GPS)",
         st == 200 and bool(created_complaint_id), f"ID: {created_complaint_id}")

# 4. AI Prediction display
has_ai = 'AI Analysis' in resp_body or 'Predicted Type' in resp_body
run_test("AI Damage Prediction & Confidence Scoring",
         has_ai and ('Pothole' in resp_body or 'High' in resp_body), "Prediction displayed")

# 5. Track page
st, url, track_body = req(citizen_opener, f"{BASE}/track?complaint_id={created_complaint_id}")
run_test("Citizen Track Page Initial State", st == 200 and 'Submitted' in track_body, "Timeline shows Submitted")

# 6. My complaints
st, url, my_comp_body = req(citizen_opener, f"{BASE}/my-complaints")
run_test("Citizen My Complaints Page", st == 200 and created_complaint_id in my_comp_body,
         f"Found {created_complaint_id}")

# 7. Admin login (invalid)
st, url, body = req(admin_opener, f"{BASE}/admin/login",
                    {'username': ADMIN_USERNAME, 'password': 'definitely-wrong-password'}, method='POST')
run_test("Admin Login Rejection (Invalid Credentials)",
         'Invalid admin credentials' in body or url.endswith('/admin/login'), "Rejected")

# 8. Admin login (valid)
st, url, _ = req(admin_opener, f"{BASE}/admin/login",
                 {'username': ADMIN_USERNAME, 'password': ADMIN_PASSWORD}, method='POST')
run_test("Admin Login (Valid Credentials)", st == 200 and 'dashboard' in url, "Redirected to dashboard")
if 'dashboard' not in url:
    print("Cannot continue without admin access. Check ADMIN_USERNAME / ADMIN_PASSWORD.")
    sys.exit(1)

# 9. Dashboard
st, url, dash_body = req(admin_opener, f"{BASE}/admin/dashboard")
dash_ok = all(k in dash_body for k in [
    'Total Complaints', 'Pending Review', 'Verified', 'Assigned', 'Repair In Progress', 'Resolved',
    'damageChart', 'severityChart', 'trendChart', 'statusChart'])
run_test("Admin Dashboard Metrics & Charts", dash_ok, "All metrics + 4 charts rendered")

# 10. Complaints list
st, url, list_body = req(admin_opener, f"{BASE}/admin/complaints")
run_test("Admin Complaints List Table", st == 200 and created_complaint_id in list_body, "Complaint listed")

# 11-13. Filters
st, url, body = req(admin_opener, f"{BASE}/admin/complaints?severity=High")
run_test("Admin Filter by Severity", st == 200 and 'High' in body, "High severity")
st, url, body = req(admin_opener, f"{BASE}/admin/complaints?damage_type=Pothole")
run_test("Admin Filter by Damage Type", st == 200 and 'Pothole' in body, "Pothole")
st, url, body = req(admin_opener, f"{BASE}/admin/complaints?status=Submitted")
run_test("Admin Filter by Status", st == 200 and 'Submitted' in body, "Submitted")

# 14. Search
st, url, search_body = req(admin_opener, f"{BASE}/admin/complaints?search_id={created_complaint_id}")
run_test("Admin Search by Complaint ID", st == 200 and created_complaint_id in search_body,
         f"Found {created_complaint_id}")

pk = find_pk(created_complaint_id)
run_test("Resolve complaint database id", pk is not None, f"pk={pk}")
if pk is None:
    sys.exit(1)

# 15. Detail
st, url, detail_body = req(admin_opener, f"{BASE}/admin/complaints/{pk}")
run_test("Admin View Complaint Detail", st == 200 and ('AI Analysis' in detail_body or 'Location' in detail_body),
         f"Complaint #{pk} loaded")

# 16. Verify
req(admin_opener, f"{BASE}/admin/complaints/{pk}/update",
    {'action': 'verify', 'remarks': 'Field officer verified road damage on site.'}, method='POST')
_, _, check = req(admin_opener, f"{BASE}/admin/complaints/{pk}")
run_test("Admin Complaint Verification (action=verify)", 'Verified' in check, "Status Verified")

# 17. Assign
req(admin_opener, f"{BASE}/admin/complaints/{pk}/update",
    {'action': 'assign', 'department': 'Public Works Department',
     'remarks': 'Assigned for immediate asphalt patch.'}, method='POST')
_, _, check = req(admin_opener, f"{BASE}/admin/complaints/{pk}")
run_test("Admin Department Assignment (action=assign)",
         'Public Works Department' in check and 'Assigned' in check, "Assigned to PWD")

# 18. Status update
req(admin_opener, f"{BASE}/admin/complaints/{pk}/update",
    {'action': 'update_status', 'status': 'Repair In Progress',
     'remarks': 'Repair machinery and materials dispatched.'}, method='POST')
_, _, check = req(admin_opener, f"{BASE}/admin/complaints/{pk}")
run_test("Admin Status Update (action=update_status)", 'Repair In Progress' in check, "Repair In Progress")

# 19. Remarks
req(admin_opener, f"{BASE}/admin/complaints/{pk}/update",
    {'action': 'add_remarks', 'remarks': 'Road surface cleaned, asphalt leveling underway.'}, method='POST')
_, _, check = req(admin_opener, f"{BASE}/admin/complaints/{pk}")
run_test("Admin Remarks Update (action=add_remarks)", 'Road surface cleaned' in check, "Remarks saved")

# 20. Repair update
repair_fields = {
    'status': 'Resolved',
    'update_date': date.today().isoformat(),
    'remarks': 'Pothole successfully filled and compacted with hot-mix asphalt. Road fully reopened to traffic.',
}
ctype_r, body_r = encode_multipart_formdata(
    repair_fields, [('repair_image', 'repair_completed.png', TINY_PNG, 'image/png')])
req(admin_opener, f"{BASE}/admin/complaints/{pk}/repair-update",
    data=body_r, headers={'Content-Type': ctype_r}, method='POST')
_, _, after = req(admin_opener, f"{BASE}/admin/complaints/{pk}")
run_test("Admin Repair Update (Photo + Date + Remarks + Status)",
         'Pothole successfully filled' in after and 'Resolved' in after, "Repair record created")

# 21. Citizen sees repair
_, _, citizen_track = req(citizen_opener, f"{BASE}/track?complaint_id={created_complaint_id}")
run_test("Citizen View Repair Updates & Image on Track Page",
         all(s in citizen_track for s in ['Pothole successfully filled', 'Repair Updates', 'Resolved', 'repair_']),
         "Remarks, badge and repair photo visible")

# 22. Reject (use a fresh complaint so the test doesn't depend on seed data)
_, reject_cid, _ = submit_complaint(citizen_opener, 'Duplicate report, private driveway')
reject_pk = find_pk(reject_cid)
req(admin_opener, f"{BASE}/admin/complaints/{reject_pk}/update",
    {'action': 'reject', 'remarks': 'Duplicate complaint outside municipal jurisdiction.'}, method='POST')
_, _, comp2 = req(admin_opener, f"{BASE}/admin/complaints/{reject_pk}")
run_test("Admin Complaint Rejection (action=reject)", 'Closed' in comp2, "Status Closed")

# 23. Map
st, url, map_body = req(admin_opener, f"{BASE}/admin/map")
run_test("Admin Interactive Map View", st == 200 and 'adminMap' in map_body and 'complaintsData' in map_body,
         "Map loaded")

# 24. Public API
st, url, api_body = req(citizen_opener, f"{BASE}/api/complaint/{created_complaint_id}")
try:
    j = json.loads(api_body)
    api_ok = (j.get('complaint_id') == created_complaint_id and j.get('status') == 'Resolved'
              and len(j.get('repair_updates', [])) > 0)
except Exception:
    api_ok = False
run_test("Public Complaint API (/api/complaint/<id>)", api_ok, "Status + repair history returned")

# 25. Admin stats API
st, url, stats_body = req(admin_opener, f"{BASE}/api/admin/stats")
try:
    s = json.loads(stats_body)
    stats_ok = s.get('total', 0) > 0 and all(k in s for k in ('by_status', 'by_severity', 'by_damage'))
except Exception:
    stats_ok = False
run_test("Admin Statistics API (/api/admin/stats)", stats_ok, "Aggregate stats returned")

print("=" * 65)
passed = sum(1 for _, ok in results if ok)
total = len(results)
print(f"SUMMARY: {passed}/{total} TESTS PASSED ({passed / total * 100:.1f}%)")
print("=" * 65)
sys.exit(0 if passed == total else 1)