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

