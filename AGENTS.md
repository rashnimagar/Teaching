# Teaching Platform — Agent Guidelines & Working Rules

All development tasks in this workspace must adhere strictly to these principles:

1. **Phased Execution & Approval**:
   - Work one phase at a time per [PROJECT_PLAN.md](file:///c:/Users/Lenovo/Desktop/projects/Teaching/PROJECT_PLAN.md).
   - Before writing any code for a phase, provide a short plan and wait for user approval.
   - Commit after each phase with a clear, concise message.

2. **Server-Side Security & Permissions**:
   - Every view must enforce permissions (students see only their enrolled courses; only staff see the custom dashboard).
   - Deadlines, lesson access, and submission windows must be verified server-side.

3. **Secrets Management**:
   - Secrets belong strictly in `.env`, never committed to Git.
   - Always keep `.env.example` updated with all required configuration variables.

4. **Testing**:
   - Write automated tests for permissions, authorization, and deadline enforcement on every phase touching those areas.

5. **UI/UX & Accessibility**:
   - Design mobile-first and responsive (phone, tablet, desktop).
   - Always include loading, empty, and error states. Maintain strong accessibility standards.

6. **Environment & Tooling**:
   - System: Windows (PowerShell).
   - Virtual environment: `.venv`.
   - Provide PowerShell-compatible commands (`.\.venv\Scripts\Activate.ps1`, `python manage.py ...`).
