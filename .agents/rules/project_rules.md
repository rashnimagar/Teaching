# Project Working Rules — Teaching Platform

These rules govern all agent and development tasks in this workspace.

---

## 1. Phased Execution & Approval Workflow
- **One Phase at a Time**: Always work strictly on one phase at a time as outlined in `PROJECT_PLAN.md`.
- **Pre-Phase Plan & Approval**: Before writing any implementation code for a phase, present a concise, actionable plan detailing:
  - Exact components, files, and models to be created/changed.
  - Verification & testing plan.
  - Wait for explicit user approval before proceeding to implementation.
- **Phase Completion & Git Commits**:
  - Review work against the "Definition of done" before closing each phase.
  - Commit after each phase with a clear, conventional commit message (e.g., `feat(phase-1): project setup with django, tailwind, and split settings`).

---

## 2. Server-Side Security & Permissions
- **Server-Side Enforcement**: Deadlines, course access, lesson visibility, and submission eligibility must **always** be validated server-side. Never rely on frontend/client-side constraints alone.
- **Strict View Permissions**:
  - Students must only access courses/lessons they are actively enrolled in (or preview lessons).
  - Custom dashboard and administrative actions must be restricted to staff/teacher users.
  - Return clean 403 Forbidden or friendly restricted-access prompts when unauthorized.

---

## 3. Secrets & Environment Configuration
- **Zero Secrets in Code or VCS**: API keys, database credentials, secret keys, and OAuth client credentials must reside exclusively in `.env`.
- **Maintain `.env.example`**: Whenever a new environment variable is introduced, immediately update `.env.example` with dummy/descriptive placeholder values.
- Verify `.env` is listed in `.gitignore` from Day 1.

---

## 4. Automated Testing Requirements
- Every phase touching business logic must include automated tests (`pytest` or `django.test.TestCase`).
- Mandatory test coverage for:
  - View permissions and authorization barriers (student vs. staff vs. unauthenticated).
  - Deadline logic (on-time submission vs. late submission vs. rejected after deadline).
  - Enrollment state transitions and access checks.

---

## 5. UI/UX, Mobile-First & Accessibility
- **Mobile-First Design**: Implement responsive layouts that look polished across mobile phones, tablets, and desktops.
- **State Handling**: Ensure UI components provide:
  - Loading states (skeletons / spinners during async or media fetch).
  - Empty states (helpful messages when no courses, submissions, or lessons exist).
  - Error states (accessible, human-readable form and server errors).
- **Accessibility**: Use semantic HTML, adequate contrast, keyboard navigation, and proper ARIA labels.

---

## 6. Environment & Command Conventions
- **OS & Shell**: Windows environment using **PowerShell**.
- **Virtual Environment**: Use the `.venv` virtual environment in the project root:
  - Activation: `.\.venv\Scripts\Activate.ps1`
  - Python execution: `python manage.py ...` (or explicit `.\.venv\Scripts\python.exe manage.py ...`)
- Provide terminal commands formatted specifically for Windows PowerShell.
