# Teaching Platform

A production-grade Django teaching platform engineered for distraction-free video courses and timed assignment submissions, with built-in future readiness for paid courses and payment gateways.

---

## Technical Stack & Architecture

- **Backend Framework:** Django 5.2 LTS (Python 3.13)
- **Database:** SQLite (local dev), PostgreSQL ready (production via `DATABASE_URL`)
- **Authentication:** Custom email-only `User` model, role-based (`student` / `teacher`), designed for `django-allauth` Google SSO
- **CSS / UI:** Modern Tailwind CSS compiled via standalone `django-tailwind-cli` (no Node.js required)
- **Static Assets:** WhiteNoise compressed & manifest storage in production; local file storage in dev
- **Cache:** Local memory (`locmem`) in dev, Redis/database cache in production
- **Code Quality:** `ruff` (linting & formatting), `pre-commit`, `pytest`, `pytest-django`, GitHub Actions CI

---

## Windows (PowerShell) Setup Guide

### 1. Prerequisites
Ensure Python 3.13 is installed on your Windows machine:
```powershell
python --version
```

### 2. Virtual Environment Setup
Clone or enter the project directory, create the `.venv` virtual environment, and activate it:
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

### 3. Install Dependencies
Install development dependencies:
```powershell
pip install -r requirements/dev.txt
```

### 4. Configure Environment
Copy `.env.example` to `.env`:
```powershell
Copy-Item .env.example .env
```
*(The defaults in `.env` are pre-configured for instant local development with SQLite)*

### 5. Run Migrations & Build Tailwind CSS
```powershell
python manage.py makemigrations accounts
python manage.py migrate
python manage.py tailwind build
```

### 6. Start the Development Server
```powershell
python manage.py runserver
```
Visit [http://127.0.0.1:8000/](http://127.0.0.1:8000/) to access the platform.

---

## Environment Variables Reference

| Variable | Description | Development Default | Production Required |
|---|---|---|---|
| `SECRET_KEY` | Cryptographic signing key | Placeholder dev key | **Yes** (strict fail-fast) |
| `DEBUG` | Django debug mode | `True` | `False` |
| `ALLOWED_HOSTS` | Comma-separated allowed hostnames | `localhost,127.0.0.1` | **Yes** (strict fail-fast) |
| `DATABASE_URL` | Database connection string | `sqlite:///db.sqlite3` | **Yes** (e.g., PostgreSQL) |
| `TIME_ZONE` | Application timezone | `Asia/Kathmandu` | `Asia/Kathmandu` |
| `MEDIA_STORAGE_BACKEND` | Storage class for user uploads | `FileSystemStorage` | S3 / R2 compatible class |
| `CACHE_URL` | Cache backend connection URI | `locmemcache://` | `redis://...` or DB cache |
| `EMAIL_BACKEND` | Django email backend | `console.EmailBackend` | `smtp.EmailBackend` |
| `EMAIL_HOST` | SMTP server host | *(empty)* | SMTP provider host |
| `EMAIL_PORT` | SMTP server port | `587` | `587` or `465` |
| `EMAIL_HOST_USER` | SMTP username | *(empty)* | SMTP credentials |
| `EMAIL_HOST_PASSWORD` | SMTP password | *(empty)* | SMTP credentials |
| `EMAIL_USE_TLS` | Enable TLS encryption | `True` | `True` |
| `DEFAULT_FROM_EMAIL` | Sender address for system emails | `Teaching Platform <...>` | Valid sender address |
| `GOOGLE_CLIENT_ID` | Google OAuth 2.0 Client ID | *(empty)* | **Yes** (from GCP Console) |
| `GOOGLE_CLIENT_SECRET` | Google OAuth 2.0 Client Secret | *(empty)* | **Yes** (from GCP Console) |
| `RATELIMIT_IP_META_KEY` | Request header for client IP extraction | `REMOTE_ADDR` | `HTTP_X_FORWARDED_FOR` (behind proxy) |
| `SENTRY_DSN` | Sentry telemetry DSN | *(empty)* | Optional DSN |

---

## Authentication & Identity

The platform supports both **Email & Password Authentication** and **Google Single Sign-On** via `django-allauth`.

### Security & Verification Guarantees
- **Mandatory Email Verification:** Newly registered student accounts must verify their email address before their first login (`ACCOUNT_EMAIL_VERIFICATION = "mandatory"`).
- **Password Strength:** Minimum 10 characters with passphrase support and live client-side guidance.
- **Pre-Hijacking Protection:** If an attacker attempts to pre-register an unverified password account for an email address, when the legitimate owner signs in via verified Google OAuth, account ownership is claimed by the Google user and the previous unverified password is automatically invalidated.
- **Anti-Enumeration:** Password reset and registration flows provide identical feedback regardless of whether an email address is already registered in the system. Duplicate signup attempts send an alert email directly to the registered account owner.
- **Honeypot Protection:** Registration forms include an invisible honeypot field (`website`) to deflect automated bot submissions.
- **Role Enforcement:** All public signups are strictly pinned to `role=student`. Teacher and administrative permissions can only be granted via `python manage.py promote_teacher` or the Django admin.

### File Upload Security & Submissions
All student assignment submissions uploaded to the platform are validated through multi-layer verification:
- **Private Storage:** Files are stored under random, unguessable UUID filenames in private storage (`STORAGES["private"]`), never directly accessible via public web URLs.
- **Permission-Checked Downloads:** Files can only be downloaded through authenticated, permission-checked endpoints by the student who submitted the file or authorized staff.
- **Format Allowlist & Real Content Inspection:** Only allowed formats (`pdf`, `docx`, `pptx`, `txt`, `png`, `jpg`/`jpeg`) are accepted. Extensions, MIME types, magic byte signatures, Office XML structures, and image pixel dimensions are strictly validated server-side. Macro-enabled documents (`vbaProject.bin`), zip bombs, executable binaries (`PE`, `ELF`), and filenames with dangerous intermediate extensions (e.g. `file.exe.pdf`) are rejected.
- **Security Notice:** *Note that server-side file type and structural validation significantly reduces attack surface and operational risk, but is not an antivirus scanner.* For high-volume production deployments, consider integrating an asynchronous antivirus daemon (e.g., ClamAV) as noted in [DEFERRED.md](file:///c:/Users/Lenovo/Desktop/projects/Teaching/DEFERRED.md).

### Google OAuth 2.0 Configuration
1. Go to the [Google Cloud Console Credentials](https://console.cloud.google.com/apis/credentials).
2. Create an **OAuth 2.0 Client ID** (Application type: *Web application*).
3. Add the exact **Authorized redirect URIs**:
   - **Local Development:**
     - `http://127.0.0.1:8000/accounts/google/login/callback/`
     - `http://localhost:8000/accounts/google/login/callback/`
   - **Production:**
     - `https://yourdomain.com/accounts/google/login/callback/`
4. Copy the Client ID and Client Secret into your `.env` file:
   ```env
   GOOGLE_CLIENT_ID="your-client-id.apps.googleusercontent.com"
   GOOGLE_CLIENT_SECRET="your-client-secret"
   ```

> [!WARNING]
> **OAuth Consent Screen: Testing vs. Production**
> In Google Cloud Console, newly created OAuth consent screens are set to **Testing** mode by default. In Testing mode, **only explicitly added test accounts** can log in. Publish the app to "In production" before launching to students.

---

## Email Delivery & SPF / DKIM Configuration

- **Development:** Uses `EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"` automatically in `dev.py`. Verification links and password reset links print directly to your terminal.
- **Production SMTP:** Driven by `.env` variables (`EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL`).
- **SPF & DKIM Domain Authentication:** To ensure verification and password reset emails reliably reach student inboxes and do not land in spam:
  - Configure **SPF** (`v=spf1 include:sendgrid.net ~all` or your provider's include) on your root sending domain.
  - Add **DKIM** CNAME/TXT records provided by your SMTP service (Postmark, SendGrid, Amazon SES, Resend).
  - Configure a basic **DMARC** policy (`v=DMARC1; p=none; rua=mailto:dmarc-reports@yourdomain.com`).
  - Set `DEFAULT_FROM_EMAIL="Your Academy <noreply@yourdomain.com>"` matching the authenticated domain.

---

## Rate Limiting & Proxy Configuration

- **Allauth Rate Limits:** Uses built-in `ACCOUNT_RATE_LIMITS` for `login`, `login_failed`, `signup`, `reset_password`, and `confirm_email`.
- **Admin Rate Limiting:** `/admin/login/` is wrapped with a strict `20/m` per IP rate limit.
- **Shared Cache Requirement:** In production with multi-worker Gunicorn or horizontal scaling, rate limits **require a shared cache backend** (such as Redis via `CACHE_URL=redis://127.0.0.1:6379/1`). Local memory caching is process-isolated and will not aggregate limits across workers.
- **Proxy Client IP:** In production behind a reverse proxy (Nginx, Caddy, Cloudflare, AWS ALB), set `RATELIMIT_IP_META_KEY=HTTP_X_FORWARDED_FOR` in `.env` to ensure rate limiting tracks real client IPs rather than the proxy IP.


## Video Streaming & Embed Security

- **Supported Providers:** Bunny Stream, Vimeo (including unlisted videos with privacy hash `video_hash`), and privacy-enhanced YouTube (`youtube-nocookie.com`).
- **Sandboxed Iframe:** Embeds use strict iframe sandboxing (`sandbox="allow-scripts allow-same-origin allow-presentation allow-popups allow-popups-to-escape-sandbox"`), lazy loading, and `referrerpolicy="strict-origin-when-cross-origin"` so provider domain checks (such as Bunny Allowed Referrers) function properly and YouTube interactive buttons open safely.
- **Bunny Stream Signed URLs:** Optional server-side token authentication is supported via `BUNNY_STREAM_SIGNING_ENABLED=True`, using SHA-256 tokens per Bunny Stream specifications (`token_key + video_id + expires`).
- **Playback Tracking:** Integrated with Player.js for Bunny Stream and Vimeo to automatically resume and record playback position periodically.

---

## Course Materials & Download Security

The platform supports course materials with three configurable download policies:
- `request_required`: Students must request access. Teachers review, approve (with optional expiry), or deny requests in the Permissions queue. No inline browser viewing is offered.
- `open_to_enrolled`: Any actively enrolled student can download the file directly.
- `view_only`: Restricted exclusively to PDF documents and image files. Files can be viewed inline in the browser, but direct download endpoints strictly reject requests with HTTP 403.

> [!NOTE]
> **Deterrent Notice:** `view_only` is an architectural deterrent against casual sharing and bulk saving, not cryptographically unbreakable protection. A determined user with local browser developer tools can inspect DOM network buffers.

---

## Common Developer Commands (PowerShell)

### Migrations
```powershell
# Create migrations for modified apps
python manage.py makemigrations

# Apply migrations
python manage.py migrate
```

### Tailwind CLI
```powershell
# Build minified CSS for distribution
python manage.py tailwind build

# Watch for CSS & template changes during active development
python manage.py tailwind watch
```

### Testing & Quality Checks
```powershell
# Run automated test suite with pytest
pytest

# Check code formatting and linting with Ruff
ruff check .
ruff format --check .

# Automatically fix lint issues and format
ruff check --fix .
ruff format .

# Django system checks
python manage.py check
```

### Administrative & Teacher Management
```powershell
# Create a superuser / developer administrator
python manage.py createsuperuser

# Promote or pre-provision a teacher account by email
# (Creates the account with an unusable password if it doesn't exist yet,
#  so the teacher's first Google login seamlessly links to teacher role)
python manage.py promote_teacher teacher@example.com
```

---

## Attributions & Font Licenses

All self-hosted web fonts bundled with this platform are open-source and distributed under the **SIL Open Font License (OFL) 1.1**:

- **Inter**: Designed by Rasmus Andersson. Licensed under SIL Open Font License 1.1. [Source](https://rsms.me/inter/)
- **Plus Jakarta Sans**: Designed by Tokotype. Licensed under SIL Open Font License 1.1. [Source](https://github.com/tokotype/PlusJakartaSans)
- **Noto Sans Devanagari**: Designed by Google Fonts. Variable woff2 font subset covering Devanagari conjuncts (`U+0900-097F`, `U+200C-200D`, `U+25CC`). Licensed under SIL Open Font License (OFL) 1.1. [Source](https://fonts.google.com/noto/specimen/Noto+Sans+Devanagari)
