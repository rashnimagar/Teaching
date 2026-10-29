# Security Policy & Implementation Record

This document outlines the security controls, HTTP response headers, Content Security Policy (CSP), cookie configurations, and defensive architectural decisions implemented in the Teaching Platform (Phase 8A).

---

## 1. Security Controls & Headers Checklist

| Item / Header | Category | Status | Evidence / Implementation Details |
| :--- | :--- | :--- | :--- |
| **Content-Security-Policy: `default-src`** | CSP | **Enforced** | `'self'`. Configured in `CSP_DIRECTIVES` in [config/settings/base.py](file:///c:/Users/Lenovo/Desktop/projects/Teaching/config/settings/base.py#L309). |
| **Content-Security-Policy: `script-src`** | CSP | **Enforced** | `'self'`. Zero executable inline `<script>` tags across all templates. Logic migrated to [static/js/auth.js](file:///c:/Users/Lenovo/Desktop/projects/Teaching/static/js/auth.js), [static/js/dashboard.js](file:///c:/Users/Lenovo/Desktop/projects/Teaching/static/js/dashboard.js), and [static/js/components.js](file:///c:/Users/Lenovo/Desktop/projects/Teaching/static/js/components.js). |
| **Content-Security-Policy: `style-src`** | CSP | **Enforced** | `'self'`. Zero inline `style=""` attributes in HTML templates. Dynamic widths & colors hydrated via CSSOM (`el.style.width = ...`) in `components.js`. |
| **Content-Security-Policy: `img-src`** | CSP | **Enforced** | `'self' data: https://i.ytimg.com`. Limited exclusively to platform assets and verified YouTube video facade thumbnails (Vimeo CDN removed as unused). |
| **Content-Security-Policy: `font-src`** | CSP | **Enforced** | `'self'`. All fonts served locally via static files. |
| **Content-Security-Policy: `connect-src`** | CSP | **Enforced** | `'self'`. AJAX requests (mark complete, position save, notifications) strictly target internal API endpoints. |
| **Content-Security-Policy: `frame-src`** | CSP | **Enforced** | `https://www.youtube-nocookie.com https://player.vimeo.com https://iframe.mediadelivery.net`. Strictly limited to authorized privacy-enhanced video hosts. Augmented dynamically on `material_preview_view` and `course_materials_view` with `'self'` for isolated PDF previews. |
| **Content-Security-Policy: `form-action`** | CSP | **Enforced** | `'self' https://accounts.google.com`. Permits internal forms and Google OAuth redirection. |
| **Content-Security-Policy: `upgrade-insecure-requests`** | CSP | **Enforced (Prod)** | Configured as `True` in `PROD_CSP_DIRECTIVES` in [config/settings/prod.py](file:///c:/Users/Lenovo/Desktop/projects/Teaching/config/settings/prod.py#L55). |
| **500.html Inline Style Hash** | CSP Exception | **Enforced** | Standalone `500.html` inline CSS allowed via SHA-256 hash (`'sha256-uQIpz7QjkwXF+rscuYjv3KPOjkTSUYCMyImb30AdrL8='`) attached to `style-src` solely on `handler500` responses in [apps/core/views.py](file:///c:/Users/Lenovo/Desktop/projects/Teaching/apps/core/views.py#L130). |
| **Django Admin CSP Policy** | CSP Exception | **Excluded by Design** | Excluded via `EXCLUDE_URL_PREFIXES = [ADMIN_URL_PREFIX]`, driven dynamically by `DJANGO_ADMIN_URL = env("DJANGO_ADMIN_URL", default="admin/")`. Django admin relies on inline scripts/styles for inlines and widgets; admin is protected by rate-limited login, strong passwords, and staff permissions. |
| **CSRF Cookie HttpOnly** | Cookies | **Enforced (Prod)** | `CSRF_COOKIE_HTTPONLY = True` in [config/settings/prod.py](file:///c:/Users/Lenovo/Desktop/projects/Teaching/config/settings/prod.py#L48). Frontend scripts read CSRF token from `<meta name="csrf-token">` or hidden input via `window.getCsrfToken()`. |
| **CSRF Cookie Secure** | Cookies | **Enforced (Prod)** | `CSRF_COOKIE_SECURE = True` in [config/settings/prod.py](file:///c:/Users/Lenovo/Desktop/projects/Teaching/config/settings/prod.py#L47). |
| **Session Cookie HttpOnly** | Cookies | **Enforced (Prod)** | `SESSION_COOKIE_HTTPONLY = True` in [config/settings/prod.py](file:///c:/Users/Lenovo/Desktop/projects/Teaching/config/settings/prod.py#L48). |
| **Session Cookie Secure** | Cookies | **Enforced (Prod)** | `SESSION_COOKIE_SECURE = True` in [config/settings/prod.py](file:///c:/Users/Lenovo/Desktop/projects/Teaching/config/settings/prod.py#L46). |
| **Referrer-Policy** | Headers | **Enforced** | `SECURE_REFERRER_POLICY = "same-origin"` site-wide in [config/settings/prod.py](file:///c:/Users/Lenovo/Desktop/projects/Teaching/config/settings/prod.py#L49). Video embed iframes explicitly declare `referrerpolicy="strict-origin-when-cross-origin"`. |
| **Cross-Origin-Opener-Policy (COOP)** | Headers | **Enforced** | `same-origin` injected by [apps/core/middleware.py](file:///c:/Users/Lenovo/Desktop/projects/Teaching/apps/core/middleware.py#L58) to isolate browsing context. |
| **Cross-Origin-Resource-Policy (CORP)** | Headers | **Enforced** | `same-origin` injected by [apps/core/middleware.py](file:///c:/Users/Lenovo/Desktop/projects/Teaching/apps/core/middleware.py#L62) on all file attachments, `FileResponse` streams, and CSV exports. |
| **Permissions-Policy** | Headers | **Enforced** | Disables `camera=()`, `microphone=()`, `geolocation=()`, `payment=()`, `usb=()`. Delegates `fullscreen`, `autoplay`, and `picture-in-picture` to `'self'` and authorized video providers in [apps/core/middleware.py](file:///c:/Users/Lenovo/Desktop/projects/Teaching/apps/core/middleware.py#L40). |
| **X-Content-Type-Options** | Headers | **Enforced** | `nosniff` enforced via Django SecurityMiddleware. |
| **X-Frame-Options** | Headers | **Enforced** | `DENY` enforced via Django Clickjacking middleware. |
| **HTTP Strict Transport Security (HSTS)** | Transport | **Enforced (Prod)** | `SECURE_HSTS_SECONDS = 86400` (1 day initial rollout), `SECURE_HSTS_INCLUDE_SUBDOMAINS = False`, `SECURE_HSTS_PRELOAD = False` in [config/settings/prod.py](file:///c:/Users/Lenovo/Desktop/projects/Teaching/config/settings/prod.py#L43). |
| **Silenced System Check `security.W021`** | System Checks | **Silenced with Rationale** | Documented rationale below. Added to `SILENCED_SYSTEM_CHECKS` in [config/settings/base.py](file:///c:/Users/Lenovo/Desktop/projects/Teaching/config/settings/base.py#L305). |
| **Session Inactivity Timeout** | Session | **Configured** | `SESSION_IDLE_TIMEOUT_SECONDS = 0` (disabled by default) in [config/settings/base.py](file:///c:/Users/Lenovo/Desktop/projects/Teaching/config/settings/base.py#L302). Position-save requests refresh activity. |
| **Inline Event Handlers** | Sanitization | **Eliminated (0 Remaining)** | Audited all 44 inline `on*=` handlers; refactored to declarative data attributes and static event listeners. |
| **`javascript:` Pseudo-URLs** | Sanitization | **Eliminated (0 Remaining)** | Verified 0 occurrences across all HTML templates. |

---

## 2. Key Architectural Decisions & Rationales

### 1. Django Admin CSP Exclusion
- **Decision:** Exclude `/admin/` from Content-Security-Policy enforcement via `EXCLUDE_URL_PREFIXES = ["/admin/"]`.
- **Rationale:** Django's core admin suite (inline formsets, calendar widgets, filter dropdowns) heavily relies on inline scripts and styles dynamically emitted by Django core form widgets. Attempting to enforce a non-inline policy or rewriting Django internal admin widgets introduces severe fragility across Django minor upgrades.
- **Compensating Controls:** Django admin is isolated under a dedicated URL path, protected by rate-limited login attempts (`rate_limited_admin_login_view` with 5 attempts per 5 minutes per IP and user), strict `is_staff` permission checks, same-origin COOP, and Clickjacking protection (`X-Frame-Options: DENY`).

### 2. Staged HSTS Rollout & Silencing `security.W021`
- **Decision:** Set initial production HSTS max-age to 86,400 seconds (1 day), keep `includeSubDomains = False` and `preload = False`, and silence Django check `security.W021`.
- **Rationale:** System check `security.W021` warns whenever `SECURE_HSTS_PRELOAD` is `False` or `SECURE_HSTS_SECONDS` is less than 31,536,000 (1 year). However, committing immediately to a multi-year preloaded HSTS policy on a newly deployed domain is an anti-pattern: any TLS misconfiguration or subdomain discrepancy renders the domain inaccessible with no recovery path. Best practice is a phased rollout:
  1. Phase 1: 1 day (`86400s`) without preload or subdomains (current).
  2. Phase 2: After 30 days of clean operations, increase to 1 month (`2592000s`).
  3. Phase 3: Transition to 1 year (`31536000s`), enable `includeSubDomains` (once all subdomains have HTTPS certificates), and submit for HSTS preload.
- Silencing `security.W021` prevents CI/deployment checks from failing while this intentional, prudent rollout is executed.

### 3. Dynamic Progress Bars Without `style-src-attr 'unsafe-inline'`
- **Decision:** Replace inline `style="width: {{ ... }}%;"` attributes with `data-progress="{{ ... }}"` and hydrate dynamically via JavaScript CSSOM (`el.style.width = ...`).
- **Rationale:** Allowing `style-src-attr 'unsafe-inline'` weakens CSP against CSS-based data exfiltration. Using CSSOM property assignment sets the computed inline width at runtime without triggering CSP style-attribute parse violations.

### 4. DOM-Grounded CSRF Token Retrieval
- **Decision:** Set `CSRF_COOKIE_HTTPONLY = True` in production and expose `<meta name="csrf-token" content="{{ csrf_token }}">` in [templates/base.html](file:///c:/Users/Lenovo/Desktop/projects/Teaching/templates/base.html#L13).
- **Rationale:** Historically, Django single-page or AJAX interactions read `document.cookie` (`getCookie("csrftoken")`), requiring `CSRF_COOKIE_HTTPONLY = False`. By rendering the token into a `<meta>` tag on authenticated and public HTML responses, static scripts can retrieve the token safely via `window.getCsrfToken()` while keeping the CSRF cookie inaccessible to client-side JavaScript, mitigating XSS token harvesting.

### 5. Isolated In-Browser PDF/Image Preview
- **Decision:** Restrict framing globally via `frame-ancestors 'none'`, and configure `X-Frame-Options: SAMEORIGIN`, `frame-ancestors 'self'`, and `frame-src 'self'` exclusively on `material_preview_view` (`apps/courses/views_materials.py`), paired with an accessible modal using `<iframe>` (zero `<embed>` or `<object>` tags).
- **Rationale:** Embedding PDFs in iframes requires the nested resource to explicitly permit being framed by `'self'`. Keeping site-wide `frame-ancestors 'none'` prevents clickjacking across all platform pages while enabling secure, isolated viewing of course handouts and documents without opening external tabs or exposing download endpoints.

### 6. Honeypot Hardening Against Screen Reader Disruption
- **Decision:** Rename the signup honeypot to a non-obvious name (`organization_code`), strip allauth's default inline `style`, and place it in an off-screen container (`absolute -left-[9999px] -top-[9999px] opacity-0 pointer-events-none h-0 w-0 overflow-hidden`) with `aria-hidden="true"`, `tabindex="-1"`, and `autocomplete="off"`.
- **Rationale:** Standard `sr-only` classes expose the field to screen reader users who may inadvertently fill it and fail registration. Off-screen positioning combined with `aria-hidden="true"` and `tabindex="-1"` ensures assistive technologies completely skip the field, while automated bots traversing the DOM are caught.

### 7. CSSOM Color Sanitization
- **Decision:** Validate `data-bg-color` values against a strict regex (`SAFE_COLOR_REGEX`) before assigning to `element.style.backgroundColor`.
- **Rationale:** Prevents arbitrary CSS injection, malicious URLs, or expression payloads from being executed via dynamic color attributes.


---

## 3. Report-Only Audit Findings & Fixes Log

During the initial report-only rollout phase, the following violations and non-conformances were detected and resolved:

1. **Inline Event Handlers (44 violations):**
   - *Detected:* `onchange="this.form.submit()"` in filters; `onclick="return confirm(...)"` and `onclick="window.location.reload()"` in action buttons; `onclick="openModal(...)"` in modals.
   - *Fix:* Replaced with declarative HTML attributes (`data-auto-submit`, `data-confirm`, `data-action="reload"`, `data-modal-open`, `data-modal-close`) wired via static listeners in `components.js` and `dashboard.js`.
2. **Inline Executable Script Blocks (17 violations):**
   - *Detected:* Inline `<script>` elements in authentication pages (`login.html`, `signup.html`, `password_reset.html`), dashboard permissions, lesson forms, and course management.
   - *Fix:* Extracted and modularized into static files (`static/js/auth.js` and `static/js/dashboard.js`), loading with `defer`.
3. **Standalone 500 Page Inline Styles (1 violation):**
   - *Detected:* `500.html` requires embedded styles to display reliably during complete application or static asset failure.
   - *Fix:* Calculated SHA-256 hash (`'sha256-uQIpz7QjkwXF+rscuYjv3KPOjkTSUYCMyImb30AdrL8='`) and injected it into `style-src` specifically on `handler500` responses in `apps/core/views.py`.
4. **Missing Referrer-Policy on Video Iframes (1 violation):**
   - *Detected:* `templates/courses/materials_list.html` iframe embed lacked `referrerpolicy`.
   - *Fix:* Added `referrerpolicy="strict-origin-when-cross-origin"` and sandbox restrictions.
5. **Missing Cross-Origin-Resource-Policy (CORP) on Downloads:**
   - *Detected:* File attachments and CSV exports were served without `Cross-Origin-Resource-Policy`.
   - *Fix:* Added middleware detection in `SecurityHeadersMiddleware` to automatically append `Cross-Origin-Resource-Policy: same-origin` to `FileResponse` and attachment responses.

---

## 4. Verification & Automated Test Suite

Automated regression tests are maintained in [tests/core/test_security_headers.py](file:///c:/Users/Lenovo/Desktop/projects/Teaching/tests/core/test_security_headers.py):
- `test_enforced_csp_present_on_public_pages`: Verifies strict CSP on public routes.
- `test_django_admin_excluded_from_csp`: Verifies admin exclusion.
- `test_permissions_policy_header`: Verifies restricted device permissions and video delegation.
- `test_coop_header`: Verifies `Cross-Origin-Opener-Policy: same-origin`.
- `test_500_style_hash_computation_matches_template`: Asserts that `500.html` content matches the CSP SHA-256 hash.
- `test_corp_header_on_attachment` & `test_corp_header_on_fileresponse`: Verifies CORP header on downloads.
- `test_session_expires_after_inactivity` & `test_session_refreshed_on_active_request`: Verifies session idle timeout behavior.
- `test_zero_inline_executable_scripts_in_templates`: Static scan asserting 0 inline `<script>` tags.
- `test_zero_inline_event_handlers_in_templates`: Static scan asserting 0 `on*=` attributes.
- `test_zero_javascript_pseudo_urls_in_templates`: Static scan asserting 0 `javascript:` URLs.
- `test_video_iframes_have_referrerpolicy_and_sandbox`: Verifies iframe isolation attributes.
- `test_material_preview_isolated_frame_headers`: Asserts `X-Frame-Options: SAMEORIGIN` and CSP `frame-ancestors 'self'` on preview routes while other routes enforce `frame-ancestors 'none'`.
- `test_admin_exclusion_matches_setting`: Verifies CSP exclusion prefix matches `DJANGO_ADMIN_URL`.

AJAX security under `CSRF_COOKIE_HTTPONLY=True` is verified in [tests/core/test_csrf_ajax.py](file:///c:/Users/Lenovo/Desktop/projects/Teaching/tests/core/test_csrf_ajax.py):
- `test_lesson_toggle_complete_with_httponly_csrf`: Marks lesson complete with `X-CSRFToken` header.
- `test_playback_position_heartbeat_with_httponly_csrf`: Saves video position via AJAX with `X-CSRFToken`.
- `test_material_request_and_cancel_with_httponly_csrf`: Material access request and cancellation with HttpOnly token.
- `test_teacher_dashboard_post_with_httponly_csrf`: Dashboard policy mutation via DOM token.
- `test_missing_or_tampered_csrf_rejected_with_403`: Verifies that invalid tokens are rejected with 403.

End-to-end browser execution and CSP violation monitoring is maintained in [tests/core/test_browser_csp.py](file:///c:/Users/Lenovo/Desktop/projects/Teaching/tests/core/test_browser_csp.py):
- Marked with `@pytest.mark.browser`.
- Launches Chromium in headless mode.
- Evaluates real user navigation across Guest, Student, and Teacher roles.
- Interacts with the YouTube video facade and verifies dynamic iframe insertion.
- Opens the in-page document preview modal and verifies iframe rendering.
- Interacts with assignments, materials management, grading, FAQs, and settings.
- Tests 403, 404, and custom 500 error page with style SHA-256 hash.
- Asserts 0 `securitypolicyviolation` events and 0 CSP console errors across all pages and interactions.

---

## 5. Assignment Attachments & Isolated Previews Architecture

1. **PDF In-Browser Previews & Sandbox Exemption:**
   - Chrome/Chromium native PDF plugin (`application/pdf`) does not render inside a CSP-sandboxed response (`sandbox` token blocks plugin activation).
   - Assignment attachment and material item previews use an isolated-frame header policy:
     - `X-Frame-Options: SAMEORIGIN`
     - CSP `frame-ancestors 'self'`
     - `X-Content-Type-Options: nosniff`
     - `Cache-Control: private, no-store`
     - Explicitly omitting `sandbox` allows browser PDF engines to render seamlessly while prohibiting cross-origin framing.
2. **Access Control & Permissions:**
   - Active enrollment in the course is strictly required for students.
   - Attachments linked to draft or not-yet-opened assignments return 404 for students.
   - Attachments linked to unpublished lessons remain hidden from students until the lesson is published.
   - View-only attachments (`download_policy = "view_only"`) permit in-browser previewing (PDF/images only) but strictly forbid direct file downloads (403 Forbidden).
3. **Auditing & Privacy:**
   - Student downloads are logged in `AssignmentAttachmentDownload` with timestamps and client IP addresses resolved safely via `get_client_ip()` (handling trusted proxy headers).
   - Teacher audit dashboards never display student IP addresses, preserving student privacy while providing accountability.
4. **Cascade Deletion & ProtectedError Prevention:**
   - `AssignmentAttachment.assignment` uses `models.PROTECT` to prevent accidental loss of handouts.
   - Assignment deletion blocks with a clear explanation if student submissions exist.
   - If no submissions exist, the teacher delete view deletes attachments first within a `transaction.atomic()` block, and dispatches private file cleanup via `transaction.on_commit()`.

---

## 6. State-Changing Endpoint Inventory (Phase 8B-1)

Every state-changing (`POST`-capable) route in the production URL resolver (`config.urls`) is cataloged below. Automated tests in [tests/core/test_access_matrix.py](file:///c:/Users/Lenovo/Desktop/projects/Teaching/tests/core/test_access_matrix.py) enforce that any new `POST`-capable route has an explicit rate limit (via `@track_ratelimit` in [apps/core/ratelimit.py](file:///c:/Users/Lenovo/Desktop/projects/Teaching/apps/core/ratelimit.py)) or a documented exemption in `POST_RATELIMIT_EXEMPTIONS`, rejects missing CSRF tokens with `403`, refuses unauthorized roles, and has a working payload factory.

| URL Name | Methods | Who May Call It | CSRF | Rate Limit (Key & Rate) | Audit Logging | Idempotent |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `account_login` | `GET, POST` | `public` | Enforced | `get_client_ip: 60/m` + allauth `login_failed` (`10/m/ip`, `5/300s/key`) | Django auth signal / failed login counter | No (creates session) |
| `account_signup` | `GET, POST` | `public` | Enforced | `get_client_ip: 30/m` + allauth `signup` (`20/m/ip`) | `User` & `EmailAddress` creation timestamps | No |
| `google_login` | `GET, POST` | `public` | Enforced | `get_client_ip: 30/m` | OAuth state initiation | No |
| `account_logout` | `GET, POST` | `authenticated` | Enforced | Exempt (session termination; safe to repeat) | Session flush | Yes |
| `account_change_password` | `GET, POST` | `authenticated` | Enforced | Exempt (requires current password + active session) | Password hash update + session cycle | No |
| `account_reset_password` | `GET, POST` | `public` | Enforced | Exempt (allauth `reset_password`: `20/m/ip`, `5/m/key`) | Password reset token dispatch | Yes |
| `account_reset_password_from_key` | `GET, POST` | `public` | Enforced | Exempt (allauth `reset_password_from_key`: `20/m/ip`) | Single-use token consumed + password updated | No |
| `account_confirm_email` | `GET, POST` | `public` | Enforced | Exempt (allauth `confirm_email`: `10/m/ip`, `3/180s/key`) | `EmailAddress.verified = True` | Yes |
| `courses:enroll` | `POST` | `authenticated` | Enforced | `user: 20/m` | Creates `Enrollment` + `EnrollmentEvent` | Yes (`get_or_create`) |
| `learn:toggle_complete` | `POST` | `enrolled` | Enforced | `user: 60/m` | Updates `LessonProgress.completed_at` | No (toggles state) |
| `learn:playback_position` | `POST` | `enrolled` | Enforced | `user: 120/m` | Updates `LessonProgress.last_position_seconds` | Yes (sets position) |
| `learn:material_request` | `POST` | `enrolled` | Enforced | `user: 15/m` | Creates `DownloadRequest(status=PENDING)` | Yes (atomic constraint check) |
| `learn:material_cancel` | `POST` | `enrolled` | Enforced | `user: 30/m` | Deletes pending `DownloadRequest` | Yes |
| `assignments:detail` | `GET, POST` | `enrolled` | Enforced | `user: 10/m, user: 30/h` | Creates/updates `Submission` + `SubmissionEvent(action="submitted")` | Yes (updates active submission) |
| `notifications:mark_read` | `POST` | `authenticated` | Enforced | `user: 60/m` | Sets `Notification.read_at` | Yes |
| `notifications:mark_all_read` | `POST` | `authenticated` | Enforced | `user: 30/m` | Bulk sets `Notification.read_at` | Yes |
| `dashboard:teacher_permission_action` | `POST` | `teacher` | Enforced | `user: 60/m` | Records `DownloadRequest.decided_by`, `decided_at`, `teacher_note` + `Notification` | Yes |
| `dashboard:teacher_permissions_bulk_action` | `POST` | `teacher` | Enforced | `user: 30/m` | Bulk updates `DownloadRequest.decided_by`, `decided_at` + `Notification` | Yes |
| `dashboard:teacher_approve_for_all` | `POST` | `teacher` | Enforced | `user: 30/m` | Sets `MaterialItem.download_policy = OPEN_TO_ENROLLED` + approves pending `DownloadRequest`s | Yes |
| `dashboard:teacher_course_create` | `GET, POST` | `teacher` | Enforced | `user: 30/m` | `logger.info` course creation + `Course` timestamps | No |
| `dashboard:teacher_course_edit` | `GET, POST` | `teacher` | Enforced | `user: 30/m` | `logger.info` on unpublish + `Course` timestamps | Yes |
| `dashboard:teacher_course_archive` | `POST` | `teacher` | Enforced | `user: 30/m` | `logger.info` archive/restore + `Course.is_archived` | Yes |
| `dashboard:teacher_lesson_create` | `GET, POST` | `teacher` | Enforced | `user: 30/m` | `logger.info` lesson creation + `Lesson` timestamps | No |
| `dashboard:teacher_course_lesson_create` | `GET, POST` | `teacher` | Enforced | `user: 30/m` | `logger.info` lesson creation + `Lesson` timestamps | No |
| `dashboard:teacher_lesson_edit` | `GET, POST` | `teacher` | Enforced | `user: 30/m` | `logger.info` video change reset + `Lesson` timestamps | Yes |
| `dashboard:teacher_course_lesson_edit` | `GET, POST` | `teacher` | Enforced | `user: 30/m` | `logger.info` video change reset + `Lesson` timestamps | Yes |
| `dashboard:teacher_lesson_toggle_publish` | `POST` | `teacher` | Enforced | `user: 60/m` | `logger.info` publish state toggle | No (toggles state) |
| `dashboard:teacher_course_lesson_toggle_publish` | `POST` | `teacher` | Enforced | `user: 60/m` | `logger.info` publish state toggle | No (toggles state) |
| `dashboard:teacher_lesson_reorder` | `POST` | `teacher` | Enforced | `user: 60/m` | Updates `Lesson.order` inside `select_for_update()` | No (swaps adjacent order) |
| `dashboard:teacher_course_lesson_reorder` | `POST` | `teacher` | Enforced | `user: 60/m` | Updates `Lesson.order` inside `select_for_update()` | No (swaps adjacent order) |
| `dashboard:teacher_lesson_delete` | `POST` | `teacher` | Enforced | `user: 30/m` | `logger.info` lesson deletion | Yes |
| `dashboard:teacher_course_lesson_delete` | `POST` | `teacher` | Enforced | `user: 30/m` | `logger.info` lesson deletion | Yes |
| `dashboard:teacher_assignment_create` | `GET, POST` | `teacher` | Enforced | `user: 30/m` | `logger.info` assignment creation + `Assignment` timestamps | No |
| `dashboard:teacher_course_assignment_create` | `GET, POST` | `teacher` | Enforced | `user: 30/m` | `logger.info` assignment creation + `Assignment` timestamps | No |
| `dashboard:teacher_assignment_edit` | `GET, POST` | `teacher` | Enforced | `user: 30/m` | `logger.info` unpublish/max_score change + `Assignment` timestamps | Yes |
| `dashboard:teacher_course_assignment_edit` | `GET, POST` | `teacher` | Enforced | `user: 30/m` | `logger.info` unpublish/max_score change + `Assignment` timestamps | Yes |
| `dashboard:teacher_assignment_toggle_publish` | `POST` | `teacher` | Enforced | `user: 60/m` | `logger.info` publish state toggle | No (toggles state) |
| `dashboard:teacher_course_assignment_toggle_publish` | `POST` | `teacher` | Enforced | `user: 60/m` | `logger.info` publish state toggle | No (toggles state) |
| `dashboard:teacher_assignment_delete` | `POST` | `teacher` | Enforced | `user: 30/m` | `logger.info` assignment deletion | Yes |
| `dashboard:teacher_course_assignment_delete` | `POST` | `teacher` | Enforced | `user: 30/m` | `logger.info` assignment deletion | Yes |
| `dashboard:teacher_assignment_attachment_add` | `POST` | `teacher` | Enforced | `user: 30/m` | `logger.info` attachment upload + `AssignmentAttachment` row | No |
| `dashboard:teacher_assignment_attachment_edit` | `POST` | `teacher` | Enforced | `user: 30/m` | `logger.info` attachment update | Yes |
| `dashboard:teacher_assignment_attachment_toggle_publish` | `POST` | `teacher` | Enforced | `user: 60/m` | `AssignmentAttachment.updated_at` | No (toggles state) |
| `dashboard:teacher_assignment_attachment_reorder` | `POST` | `teacher` | Enforced | `user: 60/m` | Updates `AssignmentAttachment.order` inside `select_for_update()` | No |
| `dashboard:teacher_assignment_attachment_delete` | `POST` | `teacher` | Enforced | `user: 30/m` | `logger.info` attachment deletion + file cleanup on commit | Yes |
| `dashboard:teacher_enrollment_action` | `POST` | `teacher` | Enforced | `user: 60/m` | Creates `EnrollmentEvent` + `Notification` | Yes |
| `dashboard:teacher_enrollments_bulk_action` | `POST` | `teacher` | Enforced | `user: 30/m` | Creates `EnrollmentEvent`s + `Notification`s | Yes |
| `dashboard:teacher_enrollment_manual` | `POST` | `teacher` | Enforced | `user: 30/m` | Creates `Enrollment` + `EnrollmentEvent` + `Notification` | Yes |
| `dashboard:teacher_submission_grade` | `GET, POST` | `teacher` | Enforced | `user: 60/m` | Creates `SubmissionEvent(action="graded"/"regraded")` + `Notification` | Yes |
| `dashboard:teacher_submission_unlock` | `POST` | `teacher` | Enforced | `user: 30/m` | Creates `SubmissionEvent(action="unlocked")` | Yes |
| `dashboard:teacher_student_toggle_active` | `POST` | `teacher` | Enforced | `user: 30/m` | `logger.info` activation/deactivation + session invalidation | No (toggles state) |
| `dashboard:teacher_material_create` | `GET, POST` | `teacher` | Enforced | `user: 30/m` | `CourseMaterial` creation timestamps | No |
| `dashboard:teacher_material_edit` | `GET, POST` | `teacher` | Enforced | `user: 30/m` | `CourseMaterial.updated_at` | Yes |
| `dashboard:teacher_material_toggle_publish` | `POST` | `teacher` | Enforced | `user: 60/m` | `CourseMaterial.updated_at` | No (toggles state) |
| `dashboard:teacher_material_archive` | `POST` | `teacher` | Enforced | `user: 60/m` | `CourseMaterial.updated_at` | No (toggles state) |
| `dashboard:teacher_material_delete` | `POST` | `teacher` | Enforced | `user: 30/m` | Deletes `CourseMaterial` (blocked if `DownloadLog`/`DownloadRequest` exist) | Yes |
| `dashboard:teacher_material_item_create` | `GET, POST` | `teacher` | Enforced | `user: 30/m` | `MaterialItem` creation timestamps | No |
| `dashboard:teacher_material_item_edit` | `GET, POST` | `teacher` | Enforced | `user: 30/m` | `MaterialItem.updated_at` + file replacement cleanup | Yes |
| `dashboard:teacher_material_item_toggle_publish` | `POST` | `teacher` | Enforced | `user: 60/m` | `MaterialItem.updated_at` | No (toggles state) |
| `dashboard:teacher_material_item_delete` | `POST` | `teacher` | Enforced | `user: 30/m` | Deletes `MaterialItem` (blocked if download history exists) | Yes |
| `dashboard:teacher_material_item_reorder` | `POST` | `teacher` | Enforced | `user: 60/m` | Updates `MaterialItem.order` inside `select_for_update()` | No |
| `dashboard:teacher_material_item_policy` | `GET, POST` | `teacher` | Enforced | `user: 30/m` | Updates `MaterialItem.download_policy` + `DownloadRequest.decided_by` | Yes |
| `dashboard:teacher_settings` | `GET, POST` | `teacher` | Enforced | `user: 30/m` | Updates `SiteSettings` singleton + invalidates cache | Yes |
| `dashboard:teacher_faq_create` | `GET, POST` | `teacher` | Enforced | `user: 30/m` | `FAQItem` creation timestamps | No |
| `dashboard:teacher_faq_edit` | `GET, POST` | `teacher` | Enforced | `user: 30/m` | `FAQItem.updated_at` | Yes |
| `dashboard:teacher_faq_toggle_publish` | `POST` | `teacher` | Enforced | `user: 60/m` | `FAQItem.updated_at` | No (toggles state) |
| `dashboard:teacher_faq_reorder` | `POST` | `teacher` | Enforced | `user: 60/m` | Updates `FAQItem.order` inside `select_for_update()` | No |
| `dashboard:teacher_faq_delete` | `POST` | `teacher` | Enforced | `user: 30/m` | Deletes `FAQItem` | Yes |
| `admin_login` | `GET, POST` | `public` | Enforced | `get_client_ip: 20/m` | Django admin login session + `LogEntry` | No |
| `admin:logout` | `POST` | `teacher` / `superuser` | Enforced | Exempt (admin session termination) | Session flush | Yes |
| `admin:password_change` | `GET, POST` | `teacher` / `superuser` | Enforced | Exempt (requires current password + staff/superuser session) | Password hash update | No |
| `admin:auth_user_password_change` | `GET, POST` | `superuser` | Enforced | Exempt (requires `change_user` permission) | Admin `LogEntry` + password hash update | No |

---

## 7. Rate Limits & Classroom-Shared IP Rationale (Phase 8B-1)

### 1. Classroom-Shared IP Design Philosophy
In a school, university computer lab, or campus Wi-Fi environment, **30 to 60 students frequently share a single outbound NAT IP address**.
- **IP-Keyed Limits (`get_client_ip` / `/ip`)** are intentionally generous (`30/m` to `60/m`) so an entire classroom logging in, signing up, or resetting passwords at the start of a lecture is never locked out by a shared NAT IP.
- **Per-Account / Per-User Limits (`user` / `/key`)** are strict (`5/300s/key` on failed login, `5/m/key` on password reset, `10/m` on assignment submission, `15/m` on material requests) to prevent brute-force credential stuffing against any target account and prevent individual user spam regardless of IP rotation.

### 2. Complete Rate Limit Registry

| Scope / Endpoint | Decorator / Setting | Key | Rate | Rationale |
| :--- | :--- | :--- | :--- | :--- |
| **Allauth: Failed Login** | `ACCOUNT_RATE_LIMITS["login_failed"]` | `ip` + `key` (email) | `10/m/ip`, `5/300s/key` | Blocks brute-force guessing against a specific email after 5 failures in 5 minutes while allowing up to 10 typos/minute across a shared classroom IP. |
| **Allauth: Signup** | `ACCOUNT_RATE_LIMITS["signup"]` | `ip` | `20/m/ip` | Allows a classroom lab of students to register concurrently while preventing automated bot mass-registration. |
| **Allauth: Password Reset Request** | `ACCOUNT_RATE_LIMITS["reset_password"]` | `ip` + `key` (email) | `20/m/ip`, `5/m/key` | Prevents email-bombing a specific user (`5/m/key`) while permitting multiple students on a shared IP to request resets (`20/m/ip`). |
| **Allauth: Password Reset Token** | `ACCOUNT_RATE_LIMITS["reset_password_from_key"]` | `ip` | `20/m/ip` | Prevents brute-forcing reset tokens from a single IP. |
| **Allauth: Email Confirmation** | `ACCOUNT_RATE_LIMITS["confirm_email"]` | `ip` + `key` | `10/m/ip`, `3/180s/key` | Prevents confirmation email flooding while allowing normal verification clicks. |
| **Login View Wrapper (`account_login`)** | `@track_ratelimit` | `get_client_ip` | `60/m` | Accommodates a 50-student classroom loading and submitting the login page simultaneously while blocking high-rate HTTP flood attacks. |
| **Signup View Wrapper (`account_signup`)** | `@track_ratelimit` | `get_client_ip` | `30/m` | Generous enough for classroom onboarding; complements allauth's `20/m/ip` POST signup limit. |
| **Google OAuth Initiation (`google_login`)** | `@track_ratelimit` | `get_client_ip` | `30/m` | Allows a classroom to sign in with Google while throttling OAuth redirect floods. |
| **Django Admin Login (`admin_login`)** | `@track_ratelimit` | `get_client_ip` | `20/m` | Only staff/superusers access the admin login; tighter IP limit (`20/m`) protects against automated scanner brute force. |
| **Course Enrollment (`courses:enroll`)** | `@track_ratelimit` | `user` | `20/m` | Authenticated per-student limit preventing enrollment request spam. |
| **Lesson Complete Toggle (`learn:toggle_complete`)** | `@track_ratelimit` | `user` | `60/m` | Per-student limit allowing normal syllabus interaction while blocking scripted toggling. |
| **Video Playback Heartbeat (`learn:playback_position`)** | `@track_ratelimit` | `user` | `120/m` | Supports periodic player heartbeats and tab-switch saves without false positives. |
| **Material Access Request (`learn:material_request`)** | `@track_ratelimit` | `user` | `15/m` | Prevents a student from flooding the teacher's permissions queue with rapid requests. |
| **Material Request Cancel (`learn:material_cancel`)** | `@track_ratelimit` | `user` | `30/m` | Per-student limit on cancelling pending download requests. |
| **Material Download & Preview (`learn:material_download`, `learn:material_preview`)** | `@track_ratelimit` | `user` | `60/m` | Allows students to preview and download course handouts smoothly while preventing automated bulk scraping. |
| **Assignment Submission (`assignments:detail` POST)** | `@track_ratelimit` | `user` | `10/m`, `30/h` | Dual window (`10/m` burst, `30/h` sustained) protects private storage and database from rapid file upload abuse. |
| **Submission & Attachment Downloads/Previews (`assignments:*`)** | `@track_ratelimit` | `user` | `60/m` | Per-user cap on streaming private submission and attachment files. |
| **Notifications (`notifications:mark_read`, `mark_all_read`)** | `@track_ratelimit` | `user` | `60/m` / `30/m` | Prevents notification state mutation spam. |
| **Teacher CSV Exports (`teacher_course_grades_export`, `teacher_course_progress_export`)** | `@track_ratelimit` | `user` | `10/m` | Protects database against expensive aggregation and CSV generation floods. |
| **Teacher Dashboard Mutations & Directory (`dashboard:teacher_*`)** | `@track_ratelimit` | `user` | `30/m` to `60/m` | Protects administrative CRUD, grading, bulk approval, and reorder endpoints against accidental loops or compromised session abuse. |

### 3. Trusted Proxy Hop Extraction & Shared Cache Enforcement
- **Unified Client IP Resolution ([apps/core/utils.py](file:///c:/Users/Lenovo/Desktop/projects/Teaching/apps/core/utils.py)):**
  - Configured via `NUM_PROXIES` (and wired identically to `ALLAUTH_TRUSTED_PROXY_COUNT`) and `TRUSTED_CLIENT_IP_HEADER` (`ALLAUTH_TRUSTED_CLIENT_IP_HEADER`).
  - `CustomAccountAdapter.get_client_ip` delegates directly to `apps.core.utils.get_client_ip`.
  - When `NUM_PROXIES = 0` (default): `X-Forwarded-For` is completely ignored and `REMOTE_ADDR` is used, preventing attackers from spoofing `X-Forwarded-For` to bypass rate limits.
  - When `NUM_PROXIES = N > 0`: reads `hops[-N]` from `X-Forwarded-For`, ignoring any fake addresses prepended by an attacker. Safely falls back to `REMOTE_ADDR` if fewer than `N` hops are present or if the hop is malformed (handling both IPv4 and IPv6 with optional ports/brackets).
- **Deploy System Check `core.E001` ([apps/core/checks.py](file:///c:/Users/Lenovo/Desktop/projects/Teaching/apps/core/checks.py)):**
  - Registered with `@register(Tags.caches, Tags.security, deploy=True)`.
  - Fails `python manage.py check --deploy --settings=config.settings.prod --fail-level ERROR` if `CACHES["default"]["BACKEND"]` is `LocMemCache` or `DummyCache`, ensuring production deployments always use a shared cross-worker cache (`RedisCache` or `DatabaseCache`).
