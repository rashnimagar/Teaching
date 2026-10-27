# Deferred Items (Final Phase)

The following items are postponed to the final hardening and production deployment phase:

## 1. Real Email Sending
- **SMTP Provider Integration:** Connect production SMTP provider (Postmark, SendGrid, Amazon SES, or Resend) via environment variables.
- **DNS / Domain Records:** Set up SPF (`v=spf1 ...`), DKIM records, and DMARC policies for the sending domain.
- **Diagnostic Management Command:** Add `python manage.py send_test_email <recipient>` to verify delivery end-to-end.
- **Failure Resilience:** Comprehensive failure logging, graceful exception handling on SMTP connection drops, and user-friendly error notices on auth forms.
- **Download Notification Emails (`NOTIFY_BY_EMAIL`):** Enable `NOTIFY_BY_EMAIL=True` in production environment variables once production SMTP and SPF/DKIM records are active. Default is `False` in development and initial deployment.

## 2. Honeypot Field Hardening (Completed in Phase 8A)
- **Field Name Obfuscation:** Renamed `website` to `organization_code`.
- **Accessibility & Bot Traps:** Added `autocomplete="off"`, `tabindex="-1"`, and `aria-hidden="true"` with off-screen positioning CSS classes (`absolute -left-[9999px] -top-[9999px] opacity-0 pointer-events-none h-0 w-0 overflow-hidden`) to completely hide from screen readers and autofill extensions.


## 3. Google OAuth Consent Screen
- **Publish to Production:** Transition Google Cloud Console OAuth consent screen status from **Testing** to **In production** so any student Google account can authenticate without being manually added to the GCP test user allowlist.
- **App Verification:** Complete Google OAuth verification for requested scopes (`profile`, `email`) if required.

## 4. Video Embed & CDN Hardening
- **Bunny Stream Token Signing:** Configure `BUNNY_STREAM_SIGNING_ENABLED=True` with production security keys to protect video content against direct URL scraping.
- **Vendor Library Documentation:** Add source URL, exact version, and open-source license attribution for `static/js/vendor/player.min.js` to `README.md`.

## 5. Production Settings & Infrastructure Review
- **Shared Cache:** Deploy and configure Redis (`django-redis` via `CACHE_URL=redis://...`) for multi-worker Gunicorn and distributed rate limit counters (Phase 8C).
- **HTTPS, CSP & Security Headers (Completed in Phase 8A):** Enforced Content-Security-Policy (CSP), `SECURE_REFERRER_POLICY = "same-origin"`, `Cross-Origin-Opener-Policy: same-origin`, `Cross-Origin-Resource-Policy: same-origin` on file downloads, `Permissions-Policy`, `CSRF_COOKIE_HTTPONLY = True`, `SESSION_COOKIE_HTTPONLY = True`, `SECURE_HSTS_SECONDS = 86400`, and silenced `security.W021` for staged rollout (detailed in `SECURITY.md`).
- **HSTS Phase 2 & 3 Escalation:** After 30 days of clean production operation, escalate HSTS duration to 30 days (`2592000s`), then 1 year (`31536000s`) with `SECURE_HSTS_INCLUDE_SUBDOMAINS = True` and submit for `SECURE_HSTS_PRELOAD = True`.
- **Error Monitoring:** Wire Sentry SDK (`sentry-sdk[django]`) with environment-based traces sample rate (Phase 8C).
- **Automated Backups:** Implement automated daily PostgreSQL database backups and media storage snapshot procedures (Phase 8C).

## 6. File Uploads & Assignment Infrastructure
- **Web-Server Upload Limits & Worker Timeouts:** Configure reverse proxy (Nginx `client_max_body_size 30M` to match `MATERIAL_MAX_FILE_SIZE_BYTES` default of 25 MB, and Gunicorn `--timeout 90`) so slow client uploads or oversized payloads are rejected early while allowing legitimate 25 MB material uploads.
- **Optional Antivirus / ClamAV Scanning:** Deploy an asynchronous background file scan hook (ClamAV daemon or containerized scanner) for uploaded student submissions in production environments with high upload volumes.
- **PostgreSQL Deadline Boundary Test:** Execute the deadline concurrency and `select_for_update` row-locking test suite against a live PostgreSQL instance prior to production launch to verify transactional isolation under high concurrent write loads.

## 7. Audit & Log Retention Policies
- **DownloadLog Retention:** Implement an automated scheduled retention task to archive or purge `DownloadLog` audit records older than 90 days in accordance with data minimization standards.
- **Notification Pruning:** Automate periodic execution of `python manage.py cleanup_old_notifications --days 90` to prune historical read notifications and keep database indexes compact.

## 8. Possible Future Features (Not Requested)
- **Unified Audit Log:** A consolidated timeline feed combining `EnrollmentEvent`, `SubmissionEvent`, and `DownloadLog` into a single administrative activity feed in the dashboard.
- **Course Announcements & Broadcasts:** Instructor-to-students broadcast messaging and course-wide announcements dispatching mass notifications.


