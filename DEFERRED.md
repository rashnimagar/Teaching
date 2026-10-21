# Deferred Items (Final Phase)

The following items are postponed to the final hardening and production deployment phase:

## 1. Real Email Sending
- **SMTP Provider Integration:** Connect production SMTP provider (Postmark, SendGrid, Amazon SES, or Resend) via environment variables.
- **DNS / Domain Records:** Set up SPF (`v=spf1 ...`), DKIM records, and DMARC policies for the sending domain.
- **Diagnostic Management Command:** Add `python manage.py send_test_email <recipient>` to verify delivery end-to-end.
- **Failure Resilience:** Comprehensive failure logging, graceful exception handling on SMTP connection drops, and user-friendly error notices on auth forms.

## 2. Honeypot Field Hardening
- **Field Name Obfuscation:** Rename `website` to a non-obvious decoy attribute (e.g., `phone_secondary` or `address_line2`).
- **Accessibility & Bot Traps:** Add `autocomplete="off"`, `tabindex="-1"`, and `aria-hidden="true"` to prevent screen readers and autofill extensions from erroneously filling the hidden field.

## 3. Google OAuth Consent Screen
- **Publish to Production:** Transition Google Cloud Console OAuth consent screen status from **Testing** to **In production** so any student Google account can authenticate without being manually added to the GCP test user allowlist.
- **App Verification:** Complete Google OAuth verification for requested scopes (`profile`, `email`) if required.

## 4. Video Embed & CDN Hardening
- **Bunny Stream Token Signing:** Configure `BUNNY_STREAM_SIGNING_ENABLED=True` with production security keys to protect video content against direct URL scraping.
- **Vendor Library Documentation:** Add source URL, exact version, and open-source license attribution for `static/js/vendor/player.min.js` to `README.md`.

## 5. Production Settings & Infrastructure Review
- **Shared Cache:** Deploy and configure Redis (`django-redis` via `CACHE_URL=redis://...`) for multi-worker Gunicorn and distributed rate limit counters.
- **HTTPS & Security Headers:** Enforce `SECURE_SSL_REDIRECT = True`, `SESSION_COOKIE_SECURE = True`, `CSRF_COOKIE_SECURE = True`, HSTS, and secure proxy headers (`HTTP_X_FORWARDED_FOR` / `HTTP_X_FORWARDED_PROTO`).
- **Error Monitoring:** Wire Sentry SDK (`sentry-sdk[django]`) with environment-based traces sample rate.
- **Automated Backups:** Implement automated daily PostgreSQL database backups and media storage snapshot procedures.

## 6. File Uploads & Assignment Infrastructure
- **Web-Server Upload Limits & Worker Timeouts:** Configure reverse proxy (Nginx `client_max_body_size 12M`, Gunicorn `--timeout 60`) so slow client uploads or oversized payloads are rejected early before consuming Django application workers.
- **Optional Antivirus / ClamAV Scanning:** Deploy an asynchronous background file scan hook (ClamAV daemon or containerized scanner) for uploaded student submissions in production environments with high upload volumes.
- **PostgreSQL Deadline Boundary Test:** Execute the deadline concurrency and `select_for_update` row-locking test suite against a live PostgreSQL instance prior to production launch to verify transactional isolation under high concurrent write loads.

