---
name: frappe-api
description: Interact with Frappe/FossUnited REST API for CRUD on DocTypes, Desk assignments, child table operations, report views, file uploads, and session management. Use when reading/writing Frappe resources, assigning documents to users, querying/reporting, managing CFP submissions, uploading files, running reports, or working with the FossUnited platform.
---

# Frappe REST API

Frappe exposes both RESTful resource endpoints and RPC method endpoints at `https://fossunited.org`. The API is useful for integrations, automation, and external tools.

## Quick Reference

| Need | Endpoint |
|------|----------|
| List documents | `GET /api/resource/:DocType` |
| Read document | `GET /api/resource/:DocType/:name` |
| Create document | `POST /api/resource/:DocType` |
| Update document | `PUT /api/resource/:DocType/:name` |
| Delete document | `DELETE /api/resource/:DocType/:name` |
| Call whitelisted method | `POST /api/method/path.to.method` |
| Upload file | `POST /api/method/upload_file` |
| Run report | `POST /api/method/frappe.desk.query_report.run` |

## Authentication

### Cookie-based (browser session)

```bash
COOKIE="sid=xxxx; system_user=yes"
CSRF="xxxx"  # from page source or login response
```

Login:
```bash
curl -s 'https://fossunited.org/api/method/login' -X POST \
  -d 'usr=email&pwd=password' \
  -H 'Content-Type: application/x-www-form-urlencoded'
# Returns sid in Set-Cookie header
```

### Token-based (API key + secret, for integrations)

Generate in Desk → Settings → API Access, then:
```bash
curl -H "Authorization: token API_KEY:API_SECRET" \
  "https://fossunited.org/api/resource/User"
```

## CRUD Operations

### List documents
```bash
curl 'https://fossunited.org/api/resource/FOSS%20Event%20CFP%20Submission?fields=["name","talk_title","status"]&limit_page_length=20' \
  -H "Cookie: $COOKIE"
```

### Filters and pagination
```bash
curl 'https://fossunited.org/api/resource/FOSS%20Event%20CFP%20Submission?\
fields=["name","talk_title"]&\
filters=[["status","=","Review Pending"]]&\
order_by="creation desc"&\
limit_start=0&limit_page_length=50' \
  -H "Cookie: $COOKIE"
```

### Create document
```bash
curl -X POST 'https://fossunited.org/api/resource/ToDo' \
  -H "Cookie: $COOKIE" -H 'Content-Type: application/json' \
  -H "X-Frappe-CSRF-Token: $CSRF" \
  -d '{"description":"Test","reference_type":"FOSS Event CFP Submission","reference_name":"8s4g5qj3oq"}'
```

### Read single document (with child tables)
```bash
curl 'https://fossunited.org/api/resource/FOSS%20Event%20CFP%20Submission/8s4g5qj3oq' \
  -H "Cookie: $COOKIE" -H 'Accept: application/json'
```

### Update document
```bash
curl -X PUT 'https://fossunited.org/api/resource/FOSS%20Event%20CFP%20Submission/8s4g5qj3oq' \
  -H "Cookie: $COOKIE" -H 'Content-Type: application/json' \
  -H "X-Frappe-CSRF-Token: $CSRF" \
  -d '{"status":"Screening"}'
```

### Delete document
```bash
curl -X DELETE 'https://fossunited.org/api/resource/ToDo/{todo_name}' \
  -H "Cookie: $COOKIE" -H "X-Frappe-CSRF-Token: $CSRF"
```

## Convenience Client API Methods

All called via `POST /api/method/frappe.client.{method}` with cookie auth.

| Method | Purpose | Key params |
|--------|---------|------------|
| `get` | Fetch full document | `doctype`, `name` |
| `get_value` | Get specific fields | `doctype`, `name`, `fieldname` |
| `set_value` | Update field(s) | `doctype`, `name`, `fieldname`, `value` |
| `get_list` | List documents | `doctype`, `fields`, `filters`, `limit_page_length` |
| `get_count` | Count documents | `doctype`, `filters` |
| `insert` | Create document | `doctype`, plus all field values |
| `submit` | Submit draft | `doctype`, `name` |
| `save` | Save changes | full document dict |
| `cancel` | Cancel submitted | `doctype`, `name` |
| `delete` | Delete document | `doctype`, `name` |
| `rename_doc` | Rename document | `doctype`, `old_name`, `new_name` |
| `get_children` | Get child table rows | `doctype`, `name`, `child_fieldname` |

### Using client API (set_value example)
```bash
curl -s 'https://fossunited.org/api/method/frappe.client.set_value' \
  -X POST \
  -H "Cookie: $COOKIE" -H 'Content-Type: application/json' \
  -H "X-Frappe-CSRF-Token: $CSRF" -H 'X-Requested-With: XMLHttpRequest' \
  -d '{"doctype":"FOSS Event CFP Submission","name":"8s4g5qj3oq","fieldname":"status","value":"Screening"}'
```

### Using client API (get_list example)
```bash
curl -s 'https://fossunited.org/api/method/frappe.client.get_list' \
  -X POST \
  -H "Cookie: $COOKIE" -H 'Content-Type: application/x-www-form-urlencoded' \
  -H "X-Frappe-CSRF-Token: $CSRF" -H 'X-Requested-With: XMLHttpRequest' \
  --data-urlencode 'doctype=FOSS Event CFP Submission' \
  --data-urlencode 'fields=["name","talk_title"]' \
  --data-urlencode 'filters=[["status","=","Review Pending"]]' \
  --data-urlencode 'limit_page_length=3'
```

## Desk Assignments

### Add (assign document to users)
```bash
curl -s 'https://fossunited.org/api/method/frappe.desk.form.assign_to.add' \
  -X POST -H "Cookie: $COOKIE" -H 'Content-Type: application/json' \
  -H "X-Frappe-CSRF-Token: $CSRF" -H 'X-Requested-With: XMLHttpRequest' \
  -d '{"assign_to":["user@email.com"],"doctype":"FOSS Event CFP Submission","name":"{cfp_name}","description":"Review assignment"}'
```

### Remove
```bash
curl -s 'https://fossunited.org/api/method/frappe.desk.form.assign_to.remove' \
  -X POST -H ... \
  -d '{"assign_to":["user@email.com"],"doctype":"...","name":"..."}'
```

### Get existing assignments
```bash
curl -s 'https://fossunited.org/api/method/frappe.desk.form.assign_to.get' \
  -X POST -H ... \
  --data-urlencode 'doctype=FOSS Event CFP Submission' \
  --data-urlencode 'name=8s4g5qj3oq'
```

### Preferred: FossUnited custom API (`set_submission_reviewers`)

The built-in `assign_to.add` has a permission issue (HTTP 403 "no share permission").
Instead, use FossUnited's custom endpoint which uses `ignore_permissions=True`:

```bash
curl -s 'https://fossunited.org/api/method/fossunited.api.cfp.set_submission_reviewers' \
  -X POST \
  -H "Cookie: $COOKIE" -H 'Content-Type: application/json' \
  -H "X-Frappe-CSRF-Token: $CSRF" -H 'X-Requested-With: XMLHttpRequest' \
  -d '{
    "submission_name": "{cfp_name}",
    "reviewer_users": ["user1@email.com", "user2@email.com", "user3@email.com"]
  }'
```

This **replaces** all existing assignments with the new list (removes old, adds new).
The `ignore_permissions=True` flag in the Python backend bypasses the share permission
restriction that `assign_to.add` requires.

**Limitations:**
- `assign_to` / `reviewer_users` emails must match Frappe User account names exactly
- Session needs "share" permission on the document or gets HTTP 403 (for `assign_to.add`)
- Group assignments by CFP — send all 3 reviewers in one call

## Report Views

### frappe.desk.reportview.get (list views with aggregation)
```bash
curl -s 'https://fossunited.org/api/method/frappe.desk.reportview.get' \
  -X POST -H "Cookie: $COOKIE" -H 'Accept: application/json' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -H "X-Frappe-CSRF-Token: $CSRF" -H 'X-Requested-With: XMLHttpRequest' \
  --data-urlencode 'doctype=FOSS Event CFP Submission' \
  --data-urlencode 'fields=["name","talk_title","status"]' \
  --data-urlencode 'filters=[["event","=","ek0supi1tu"]]' \
  --data-urlencode 'order_by=modified desc' \
  --data-urlencode 'limit_page_length=100'
```
Response format: `{"message": {"keys": [...], "values": [[...], [...]]}}`

### frappe.desk.query_report.run (custom reports)
```bash
curl -s 'https://fossunited.org/api/method/frappe.desk.query_report.run' \
  -X POST -H "Cookie: $COOKIE" -H 'Content-Type: application/json' \
  -H "X-Frappe-CSRF-Token: $CSRF" -H 'X-Requested-With: XMLHttpRequest' \
  -d '{"report_name":"Report Name","filters":{}}'
```

## Child Table Operations

### Read child table entries (e.g., reviews, speakers)
```bash
curl -s 'https://fossunited.org/api/method/frappe.client.get_children' \
  -X POST -H "Cookie: $COOKIE" -H 'Content-Type: application/x-www-form-urlencoded' \
  -H "X-Frappe-CSRF-Token: $CSRF" -H 'X-Requested-With: XMLHttpRequest' \
  --data-urlencode 'doctype=FOSS Event CFP Submission' \
  --data-urlencode 'name=8s4g5qj3oq' \
  --data-urlencode 'child_parenttype=FOSS Event CFP Submission' \
  --data-urlencode 'child_fieldname=speakers'
```

### Update child tables (replace all children via PUT on parent)
```bash
curl -X PUT 'https://fossunited.org/api/resource/FOSS%20Event%20CFP%20Submission/{name}' \
  -H "Cookie: $COOKIE" -H 'Content-Type: application/json' \
  -H "X-Frappe-CSRF-Token: $CSRF" \
  -d '{"reviews": [{"reviewer":"Name","email":"e@mail.com","to_approve":"Maybe"}]}'
```

## File Uploads

```bash
curl -s 'https://fossunited.org/api/method/upload_file' \
  -X POST -H "Cookie: $COOKIE" \
  -H "X-Frappe-CSRF-Token: $CSRF" \
  -F 'file=@/path/to/file.pdf' \
  -F 'doctype=FOSS Event CFP Submission' \
  -F 'docname=8s4g5qj3oq' \
  -F 'is_private=1'
```

## Workflow Operations

```bash
# Apply workflow transition
curl -s 'https://fossunited.org/api/method/frappe.model.workflow.apply_workflow' \
  -X POST -H "Cookie: $COOKIE" -H 'Content-Type: application/json' \
  -H "X-Frappe-CSRF-Token: $CSRF" \
  -d '{"doctype":"FOSS Event CFP Submission","name":"8s4g5qj3oq","action":"Approve"}'

# Get possible transitions
curl -s 'https://fossunited.org/api/method/frappe.workflow.get_transitions' \
  -X POST -H ... \
  --data-urlencode 'doctype=FOSS Event CFP Submission' \
  --data-urlencode 'name=8s4g5qj3oq'
```

## Permission Queries

```bash
# Check permissions
curl -s 'https://fossunited.org/api/method/frappe.permissions.has_permission' \
  -X POST -H ... \
  --data-urlencode 'doctype=FOSS Event CFP Submission' \
  --data-urlencode 'ptype=write'

# Get doc-level permissions
curl -s 'https://fossunited.org/api/method/frappe.permissions.get_doc_permissions' \
  -X POST -H ... \
  --data-urlencode 'doctype=FOSS Event CFP Submission' \
  --data-urlencode 'docname=8s4g5qj3oq'
```

## Key DocTypes (FossUnited)

| Doctype | Purpose |
|---------|---------|
| `FOSS Event CFP Submission` | CFP proposals (parent doc) |
| `FOSS Event CFP Review` | Child table: review entries (reviewer, email, to_approve) |
| `CFP Submission Speaker` | Child table: speaker info |
| `CFP Submission Reference` | Child table: reference links |
| `FOSS Custom Answer` | Child table: custom questions (track field) |
| `IndiaFOSS Reviewer Signup` | Reviewer registration form |
| `FOSS User Profile` | User profile with social links |
| `FOSS Event CFP Reviewer` | Child table: reviewer assignments on event |
| `FOSS Global CFP Review Member` | Global CFP review team |
| `ToDo` | Desk assignments (reference_type, reference_name, allocated_to) |
| `User` | Frappe user accounts |
| `DocType` | System doctype metadata |

## Common Filters

```python
# IndiaFOSS 2026 CFPs:
filters = [["event", "=", "ek0supi1tu"]]

# CFPs with reviews:
filters = [["positive_reviews", ">", 0]]

# Open Desk assignments:
filters = [["reference_type", "=", "FOSS Event CFP Submission"], ["status", "=", "Open"]]

# Reviewer signups for event:
filters = [["event", "=", "ek0supi1tu"]]
```

## Error Handling

| HTTP | Meaning | Fix |
|------|---------|-----|
| 403 | Permission denied | No share/doc-level write rights; use different session or Desk |
| 417 | LinkValidationError | Referenced user/record not found; check email matches Frappe User name |
| 401 / CSRFTokenError | CSRF token expired | Fetch fresh token from login page or re-authenticate |
| 502 | Backend error | Check request format, field names, and data types |

## Enriching Frappe Data with web search + GitHub

Use the `tavily-search` skill to find reviewer/speaker social links, then
update Frappe records:

```bash
# 1. Search for person
bash ~/.pi/agent/skills/james/tavily-search/scripts/search.sh "Bodhish Thomas github" --max 3

# 2. Fetch GitHub profile for bio/blog (often has LinkedIn)
curl -s https://api.github.com/users/bodhish | python3 -c "import json,sys; d=json.load(sys.stdin); print('login:', d.get('login')); print('blog:', d.get('blog')); print('bio:', (d.get('bio') or '')[:100])"

# 3. Check rendered GitHub page for LinkedIn links
curl -s https://github.com/bodhish | grep -oP 'https?://[^\"]*linkedin[^\"]*'

# 4. Update Frappe doc with links (PATCH or set_value)
```

### Bulk enrichment workflow
1. Fetch reviewer list from `IndiaFOSS Reviewer Signup`
2. For each missing social link, search via tavily-search
3. Verify via GitHub API + HTML scrape
4. Update reviewer profile or signup record
