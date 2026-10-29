# Teacher Platform User Guide

Welcome to the Teaching Platform Teacher Portal. This guide explains how to manage your courses, lessons, assignments, student enrollments, grading, downloadable resources, site settings, and FAQs using the web interface.

---

## 1. Courses Management

The **Courses** section is your central hub for creating and organizing educational programs.

- **Creating a Course:**
  - Navigate to **Courses** from the left navigation bar and click **Create New Course**.
  - Provide a clear, descriptive **Course Title** and a concise **Short Description**.
  - Enter the full course syllabus and learning objectives in the **Course Description** area.
  - Choose whether the course is **Free** or **Paid**. For paid courses, enter the price in Nepalese Rupees (NPR).
  - Optionally check **Requires Approval** if student enrollment applications must be manually vetted before granting access.
  - Upload a landscape thumbnail image (PNG or JPG). The platform automatically optimizes and generates high-efficiency WebP images.
  - Keep the course as a **Draft** while preparing content, or check **Publish Course** when ready for public display.

- **Editing & Course Slug Locking:**
  - You can edit course information at any time from the **Edit** button.
  - For link safety and SEO integrity, the course web address (slug) is permanently locked once the course has been published or after the first student enrolls.

- **Archiving Courses:**
  - When a course is finished or retired, click **Archive**.
  - Archived courses remain intact with all student submissions, grades, and records preserved, but they are tucked away from public enrollment listings.

---

## 2. Lessons & Syllabus Organization

Inside each course, you structure your curriculum through sequential video lessons.

- **Adding Lessons:**
  - On the Courses list, click **Lessons** next to your course, then click **Add Lesson**.
  - Enter a lesson title, duration in minutes, and an optional text summary.
  - Select your video provider: **Bunny Stream**, **Vimeo**, or **YouTube**.
  - Paste the video identifier or video URL. For Vimeo or Bunny Stream, you can provide an optional privacy hash to secure private playback.
  - Check **Free Preview** if you want prospective students to watch this lesson without enrolling.

- **Reordering Lessons:**
  - Use the **Up** and **Down** arrow buttons on any lesson to arrange your syllabus sequence.
  - The platform automatically updates and normalizes lesson numbering with strict transactional safety.

- **Publishing & Deleting:**
  - Toggle a lesson between **Published** and **Draft** at any time.
  - To delete a lesson, click **Delete**. If students have already recorded lesson progress or completed linked assignments, the system will protect student data and ask you to unpublish the lesson instead.

---

## 3. Assignments & Deadlines

Assignments allow students to practice what they learn, upload homework, and receive grades and constructive feedback.

- **Creating an Assignment:**
  - From your course, click **Assignments**, then click **Create Assignment** (or click **+ Add Assignment** directly next to any lesson in the Lessons list to pre-select that lesson).
  - Enter an assignment title, detailed instructions, and the **Maximum Score** (e.g. 100).
  - Select an associated syllabus lesson from the dropdown (draft lessons are clearly marked with `(Draft)`), or choose `None (Course-wide Assignment)`.
  - Specify the **Opens At** and **Due Date & Time** in Nepal Time (NPT).
  - Decide whether to **Allow Late Submissions**. If disabled, students cannot turn in work once the deadline passes (unless granted an unlock).
  - When saving a new assignment, you are automatically redirected to the Edit page where you can upload starter files, handouts, or rubrics.

- **Assignment Attachments & Handouts:**
  - On the assignment edit page, manage attachments in the **Attachments & Starter Files** panel.
  - Upload starter code, lab guides, or rubric documents up to 25 MB in size.
  - Choose between two access policies:
    1. **Open to Enrolled Students (Default):** Enrolled students can download the file.
    2. **View Only (PDF and images only):** Direct downloading is disabled; students can only view the file directly in their browser.
  - Reorder attachments using the up/down controls, toggle visibility between Published and Hidden, or edit titles.
  - **Replacing Files:** If you replace an attachment's file, the student download history is fully preserved, and the old physical file is safely removed from storage.
  - **Download Audit:** Click the download count on any attachment to view student download records (timestamp and student identity are shown; student IP addresses are omitted for privacy).

- **Safeguards on Scores, Publishing, and Deletion:**
  - You cannot lower the maximum score below a grade that has already been awarded to a student.
  - If an assignment already contains student submissions, unpublishing requires a special confirmation to prevent accidentally hiding student grades and feedback.
  - If student submissions exist, deleting the assignment is blocked to preserve student academic records (you can unpublish it instead). If no submissions exist, attachments and their storage files are safely deleted before removing the assignment.

---

## 4. Course Materials & Downloadable Resources

Organize handouts, cheat sheets, lecture slide decks, sample code, and reference links for enrolled students.

- **Resource Containers & Items:**
  - In the course actions, click **Materials** to view and create resource containers (e.g. "Week 1 Lecture Slides").
  - Inside each container, you can add three types of items:
    1. **File Uploads:** Upload documents (PDF, Word, PowerPoint, plain text, or images) up to 25 MB in size.
    2. **External Links:** Safe web links (`http://` or `https://`) pointing to documentation, tools, or references.
    3. **Embedded Videos:** Supplementary video guides.

- **Download Access Policies:**
  - Each uploaded file has one of three access policies:
    1. **Request Required (Default):** Students must submit a request stating why they need offline access. You review and approve each request.
    2. **Open to Enrolled Students:** Any student enrolled in the course can immediately download the file without prior approval.
    3. **View Only (In-Browser Preview Only):** Strictly reserved for PDF documents and image files (PNG/JPG). Direct downloading is disabled; students can only view the content directly inside their web browser.

- **Changing Policies:**
  - Click **Policy** on any file to open the policy transition page.
  - When switching from *Open to Enrolled* to *Request Required*, you can choose to automatically preserve approved access for students who previously downloaded the file.
  - When switching to *View Only*, any pending download requests are automatically closed as denied, existing approvals are revoked, and students are notified.

- **Replacing Files:**
  - When editing a file item, uploading a new file automatically replaces the old one and cleanly deletes the superseded file from storage. All existing student download approvals remain active.

- **Deleting vs. Unpublishing Items:**
  - To protect student audit trails, an item that has download request records or download access logs **cannot be deleted**. You can unpublish it instead, which immediately hides it from students. Items without history can be safely deleted.

---

## 5. Reviewing & Approving Download Permissions

The **Permissions Queue** lets you oversee and manage student requests for offline file access.

- **Reviewing Requests:**
  - Navigate to **Permissions** in the sidebar.
  - You will see tabs for **Pending**, **Approved**, **Denied**, and **Revoked** requests.
  - Each request shows the student's name, email, requested file, and the student's stated reason.

- **Taking Action:**
  - Click **Approve** to grant immediate download access.
  - Click **Deny** to refuse access, with an optional polite note explaining the decision.
  - For files that you decide to open to all students, click **Approve for All Enrolled**. This resolves all pending requests and notifies each student.
  - Bulk actions allow you to select multiple requests and approve or deny them simultaneously.

- **Audit Download History:**
  - Click **History** on any material item or permissions record to inspect when students accessed the file.
  - For student privacy, the history displays the student name, email, file name, and exact time in Nepal Time (client IP addresses are never exposed to teachers).

---

## 6. Student Enrollments & Applications

Manage who is enrolled in your courses.

- **Enrollment Queue:**
  - Go to **Enrollments** to view active students, pending applications, and waitlisted requests.
  - Filter by course, status, or search for a student by name or email.

- **Approving & Rejecting:**
  - For courses requiring approval, click **Approve** to activate the student's course access.
  - Click **Reject** if the student does not qualify, providing an optional note.

- **Manual Enrollment:**
  - Need to give a student immediate access without them signing up through the storefront? Click **Manual Enrollment**, choose the course, enter the student's email, and select whether to grant active or pending access.

---

## 7. Grading Submissions & Managing Resubmissions

Evaluate student homework and assignments fairly and efficiently.

- **Grading Interface:**
  - Go to **Submissions** to view the grading queue.
  - Click **Grade** next to any student's submission.
  - You can read the student's written response and securely download any attached project files.
  - Enter a **Numerical Grade** (from 0 up to the maximum assignment score) and write constructive **Instructor Feedback**.
  - Click **Save & Next Ungraded** to immediately advance to the next student awaiting a score.

- **Unlocking for Resubmissions:**
  - If a student made a mistake, turned in the wrong file, or requested an opportunity to improve their work, click **Unlock for Resubmission**.
  - Enter a reason (e.g. "Allowed revision for final project").
  - Unlocking overrides the assignment deadline (even if late submissions are normally closed).
  - When the student resubmits, their updated work automatically re-enters the ungraded queue with an alert indicating that resubmitted work needs review, displaying their previous score for comparison.
  - Every unlock, submission, and grading action is permanently recorded in the **Submission Audit Trail** at the bottom of the page.

---

## 8. Exporting Grades & Progress Reports

Download comprehensive spreadsheet records for your institution or offline tracking.

- **Grades Export (CSV):**
  - On the Courses list, click **Grades CSV** next to your course.
  - Downloads a complete spreadsheet listing every enrolled student, their enrollment date, current status, score on every assignment, total earned points, and overall percentage grade.

- **Progress Export (CSV):**
  - Click **Progress CSV** next to your course.
  - Downloads an itemized record showing which lessons each student has completed, their percentage progress through the syllabus, and their last active date.

---

## 9. Global Site Settings & Branding

Customize the public appearance and branding of your platform.

- **Platform Identity:**
  - Navigate to **Site Settings** in the sidebar.
  - Edit your **Site Name**, **Hero Headline**, and **Hero Subheadline**. These texts appear directly on your homepage and across search engine previews.

- **Teacher Profile & Narrative:**
  - Enter your **Full Name**, **Professional Title**, and **Biography Narrative**.
  - Upload a high-resolution square portrait photo. The platform automatically creates modern WebP image versions and cleans up older images.
  - Note: The instructor section on the homepage remains hidden until your name and bio are filled in.

- **Social Channels:**
  - Add your verified profiles for GitHub, X (Twitter), LinkedIn, and YouTube.
  - All web addresses are checked for security and must begin with `http://` or `https://`.

- **Instant Update:**
  - Saving changes updates the platform's cache immediately. Click **Preview Home Page** at the top right to view your live changes in a new tab.

---

## 10. Frequently Asked Questions (FAQs)

Answer common student questions on your homepage.

- **Managing FAQs:**
  - Go to **FAQs** in the sidebar.
  - View all questions, their order, and whether they are live or saved as draft.
- **Adding Questions:**
  - Click **Add Question**.
  - Enter the student question and a comprehensive, helpful answer.
  - Choose whether to make it live immediately.
- **Reordering & Previews:**
  - Use the **Up** and **Down** arrows to control the sequence of questions on the homepage accordion.
  - Click **Preview on Home** to view how the questions appear to students.

---

*Thank you for educating with the Teaching Platform! For further administrative assistance, contact your system administrator.*
