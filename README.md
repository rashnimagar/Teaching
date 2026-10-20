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

## Google OAuth 2.0 Configuration

Authentication is powered by Google Single Sign-On via `django-allauth`. Students authenticate exclusively with their Google accounts (local password signup is closed).

### 1. Google Cloud Console Setup
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
> In the Google Cloud Console, newly created OAuth consent screens are set to **Testing** mode by default. In Testing mode, **only explicitly added test accounts** can log in.
> Before launching to real students, you **must publish the app to "In production"** on the Google Cloud OAuth consent screen settings.

---

## Rate Limiting & Proxy Configuration

- **Login Initiation:** Protected by a strict rate limit of `30/m` per IP address. Exceeding this limit returns a styled HTTP 429 page.
- **Proxy Client IP:** In production behind a reverse proxy (Nginx, Caddy, Cloudflare, AWS ALB), set `RATELIMIT_IP_META_KEY=HTTP_X_FORWARDED_FOR` in `.env` to ensure rate limiting accurately tracks client IPs rather than the proxy IP.
- **Shared Cache:** In production with multi-worker Gunicorn or horizontal scaling, rate limiting requires a centralized shared cache backend (e.g. Redis via `CACHE_URL=redis://...` or Django database cache) rather than in-memory storage.

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
