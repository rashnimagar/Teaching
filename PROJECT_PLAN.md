# Teaching Platform — Project Plan

A Django-based learning platform where a teacher uploads course videos, students log in with Google, watch lessons and submit assignments before deadlines. Paid courses and a payment gateway come later, so the foundation is designed for them from day one.

**Stack:** Django (latest stable), PostgreSQL-ready, Tailwind CSS, django-allauth (Google), external video host (Bunny Stream / Vimeo), Windows dev with `.venv`.

---

## Working rules (for Antigravity)

- Work **one phase at a time**. Show a short plan and wait for approval before coding each phase.
- Commit after every phase with a clear message.
- Every view must check permissions (students see only enrolled courses; only staff see the dashboard).
- Deadlines and access are enforced **server-side**, never in the browser.
- All secrets come from `.env`. Never commit keys. Keep `.env.example` updated.
- Add tests for permissions, deadlines, and (later) payments.
- Mobile-first, accessible UI with loading, empty, and error states.

---

## Roles

| Role | How they log in | Can do |
|---|---|---|
| Student | Google only | Browse courses, access enrolled courses, watch lessons, submit assignments |
| Teacher/Admin | Google (staff flag) or Django admin | Manage courses, lessons, assignments, enrollments, submissions, grades |

---

## Data model (future-proof for payments)

- **User** (Google identity, `role`)
- **Course**: title, slug, description, thumbnail, `is_published`, `is_free` (default true), `price` (nullable), `currency`
- **Lesson**: course, title, order, `video_provider`, `video_id`, duration, `is_preview`
- **Assignment**: course (optional lesson), title, instructions, `opens_at`, `due_at`, max score
- **Submission**: assignment, student, text/file, `submitted_at`, `is_late`, grade, feedback
- **Enrollment**: student, course, `status` (pending/active/revoked), `source` (manual/free/payment), `created_at`
- **LessonProgress**: student, lesson, completed_at

> Payments later add **Order** and **Payment** models. Enrollment already has `status` and `source`, so no redesign is needed.

---

## Phase 1 — Project setup
- [ ] Create project and apps (`accounts`, `courses`, `assignments`, `dashboard`, `core`)
- [ ] `.venv`, `requirements.txt`, split settings (base/dev/prod), `.env` and `.env.example`
- [ ] Tailwind setup, base template, static/media config
- [ ] Git init, `.gitignore`, first commit

## Phase 2 — Models, admin, seed data
- [ ] Implement the data model above with migrations
- [ ] Register models in Django admin (backup management tool)
- [ ] Seed command with sample courses, lessons, assignments

## Phase 3 — Authentication (Google login)
- [ ] django-allauth with Google provider, no password signup
- [ ] Google OAuth credentials via `.env`; redirect URIs for local and production
- [ ] Role handling (student by default; teacher set by admin)
- [ ] Login/logout flow and friendly error pages

## Phase 4 — Public home page
- [ ] Hero/intro about the teacher and platform
- [ ] "Available Courses" grid (thumbnail, title, description, lesson count, free/paid badge)
- [ ] Course detail page (public syllabus, locked lessons, enroll/login call to action)
- [ ] SEO basics, responsive layout

## Phase 5 — Student area
- [ ] Dashboard: enrolled courses and progress
- [ ] Course page with ordered lessons and embedded video player
- [ ] Mark lessons complete; resume where they left off
- [ ] Enrollment access check on every course/lesson view

## Phase 6 — Assignments and submissions
- [ ] Assignment list per course with live countdown
- [ ] Submit text and/or file (type and size validation)
- [ ] Server-side deadline enforcement (reject after `due_at`; handle edge case of deadline passing mid-submission)
- [ ] Student view of grade and feedback

## Phase 7 — Teacher dashboard (custom)
- [ ] Overview stats: students, submissions, upcoming deadlines
- [ ] CRUD for courses, lessons, assignments
- [ ] Enrollment management (approve, remove, add manually)
- [ ] Submissions: filter, review, grade, see who missed the deadline
- [ ] Student list with progress

## Phase 8 — Security and rate limiting
- [ ] Rate limits on login, submissions, uploads, and any API endpoints (django-ratelimit or DRF throttling)
- [ ] CSRF, secure cookies, HTTPS settings, security headers
- [ ] Signed or domain-restricted video embeds
- [ ] Upload validation, permission tests, deadline tests
- [ ] Logging and error monitoring

## Phase 9 — UI/UX polish
- [ ] Consistent design system (colors, typography, components)
- [ ] Full responsive pass (phone, tablet, desktop)
- [ ] Loading skeletons, empty states, toasts, form validation messages
- [ ] Accessibility pass (contrast, keyboard, alt text)
- [ ] Performance pass (image sizes, caching, query optimization)

## Phase 10 — Deployment
- [ ] Production settings, PostgreSQL, static/media handling
- [ ] Domain, HTTPS, Google OAuth production redirect URIs
- [ ] Backups, environment variables, basic monitoring
- [ ] Handover notes for the teacher (how to add a course, lesson, assignment)

---

## Phase 11 (Future) — Paid courses and payment gateway

**Goal:** students pay for a course and get access automatically.

### Decisions to confirm with the teacher first
- [ ] Where do students pay from (Nepal only, or international)? This decides the gateway.
- [ ] Gateway choice for Nepal: eSewa, Khalti, Fonepay, ConnectIPS
- [ ] Pricing model: one-time per course, bundles, coupons, refunds policy
- [ ] Who owns the merchant account (it should be the teacher's business)

### Build steps
- [ ] Add **Order** (student, course, amount, currency, status, created_at) and **Payment** (order, gateway, gateway_ref, raw_response, verified_at)
- [ ] Gateway abstraction layer (one interface: `initiate()`, `verify()`) so gateways can be swapped or added
- [ ] Checkout flow: create Order, redirect to gateway, handle success/failure callbacks
- [ ] **Always verify server-side** with the gateway and reconcile the paid amount against the Order before activating access
- [ ] On verified payment: create/activate Enrollment (`source=payment`), send confirmation
- [ ] Idempotency: a repeated callback must not create duplicate enrollments
- [ ] Admin/dashboard: orders list, payment status, manual enroll or refund marking, revenue summary
- [ ] Receipts/invoices, coupon codes (optional)
- [ ] Tests: success, failure, tampered amount, duplicate callback, access before/after payment
- [ ] Use sandbox/test credentials first; switch to live keys only after full testing

### Integration options
- A Django package that wraps Khalti, eSewa, Fonepay and ConnectIPS exists (`django-nepali-payment`). It is new, so review its code and pin the version before relying on it.
- Or integrate each gateway's official API directly behind the abstraction layer (more work, more control).

---

## Definition of done (per phase)
1. Feature works on desktop and mobile
2. Permissions and edge cases tested
3. No secrets committed
4. README and `.env.example` updated
5. Committed with a clear message