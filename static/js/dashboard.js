/**
 * Teaching Platform - Teacher Dashboard Static Controller
 * Handles all teacher portal UI interactions without inline scripts or event handlers.
 * Adheres strictly to CSP Level 2/3 (zero inline JS).
 */
(function () {
  'use strict';

  // 1. Teacher Mobile Navigation Drawer
  function initTeacherDrawer() {
    const toggle = document.getElementById('teacher-drawer-toggle');
    const menu = document.getElementById('teacher-sidebar-menu');
    if (toggle && menu) {
      toggle.addEventListener('click', function () {
        const isExpanded = toggle.getAttribute('aria-expanded') === 'true';
        toggle.setAttribute('aria-expanded', (!isExpanded).toString());
        menu.classList.toggle('hidden');
      });
    }
  }

  // 2. Course Form (Auto-Slug, Free Price Toggle, Unpublish Modal)
  function initCourseForm() {
    const form = document.getElementById('course-form');
    if (!form) return;

    const titleInput = document.getElementById('id_title');
    const slugInput = document.getElementById('id_slug');
    const isFreeCheckbox = document.getElementById('id_is_free');
    const priceWrapper = document.getElementById('price-field-wrapper');
    const isPublishedCheckbox = document.getElementById('id_is_published');
    const confirmUnpublishInput = document.getElementById('id_confirm_unpublish');
    const unpublishModal = document.getElementById('unpublish-modal');
    const unpublishCancel = document.getElementById('unpublish-modal-cancel');
    const unpublishConfirm = document.getElementById('unpublish-modal-confirm');

    const originallyPublished = form.getAttribute('data-originally-published') === 'true';
    const activeStudentsCount = parseInt(form.getAttribute('data-active-students') || '0', 10);
    const isSlugDisabled = slugInput ? slugInput.disabled : false;

    // Auto-slug generation
    if (titleInput && slugInput && !isSlugDisabled) {
      let slugTouched = Boolean(slugInput.value.trim());

      slugInput.addEventListener('input', function () {
        slugTouched = Boolean(this.value.trim());
      });

      titleInput.addEventListener('input', function () {
        if (slugTouched) return;
        const title = this.value.trim();
        let slug = title
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, '-')
          .replace(/^-+|-+$/g, '');

        if (!slug) {
          const randHex = Math.random().toString(36).substring(2, 8);
          slug = 'course-' + randHex;
        }
        slugInput.value = slug;
      });
    }

    // Toggle Price Field
    if (isFreeCheckbox && priceWrapper) {
      isFreeCheckbox.addEventListener('change', function () {
        if (this.checked) {
          priceWrapper.classList.add('hidden');
        } else {
          priceWrapper.classList.remove('hidden');
        }
      });
    }

    // Unpublish Confirmation Modal
    if (isPublishedCheckbox && unpublishModal) {
      form.addEventListener('submit', function (e) {
        const willBeUnpublished = originallyPublished && !isPublishedCheckbox.checked;
        const alreadyConfirmed = confirmUnpublishInput && confirmUnpublishInput.value === 'true';

        if (willBeUnpublished && activeStudentsCount > 0 && !alreadyConfirmed) {
          e.preventDefault();
          unpublishModal.classList.remove('hidden');
        }
      });

      if (unpublishCancel) {
        unpublishCancel.addEventListener('click', function () {
          unpublishModal.classList.add('hidden');
          isPublishedCheckbox.checked = true;
        });
      }

      if (unpublishConfirm) {
        unpublishConfirm.addEventListener('click', function () {
          if (confirmUnpublishInput) {
            confirmUnpublishInput.value = 'true';
          }
          unpublishModal.classList.add('hidden');
          form.submit();
        });
      }
    }
  }

  // 3. Course List (Archive / Restore Modal)
  function initCourseList() {
    const modal = document.getElementById('archive-modal');
    const modalTitle = document.getElementById('archive-modal-title');
    const modalDesc = document.getElementById('archive-modal-desc');
    const modalSubmit = document.getElementById('archive-modal-submit');
    const form = document.getElementById('archive-form');
    const cancelBtn = document.getElementById('archive-modal-cancel');

    if (!modal || !form) return;

    document.querySelectorAll('.archive-toggle-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        const slug = this.dataset.courseSlug;
        const title = this.dataset.courseTitle;
        const isArchived = this.dataset.courseArchived === 'true';
        const activeStudents = parseInt(this.dataset.activeStudents || '0', 10);

        form.action = '/dashboard/teacher/courses/' + slug + '/archive/';

        if (isArchived) {
          modalTitle.textContent = 'Restore Course: ' + title;
          modalDesc.textContent = 'Restoring this course will make it visible in the public catalog and search listings again if published.';
          modalSubmit.textContent = 'Restore Course';
          modalSubmit.className = 'px-4 py-2 rounded-xl text-xs font-semibold text-white bg-indigo-600 hover:bg-indigo-700 shadow-xs transition';
        } else {
          modalTitle.textContent = 'Archive Course: ' + title;
          modalDesc.textContent = 'Archiving hides the course from public catalog and search. Currently ' + activeStudents + ' active student(s) will keep access to learn and submit work.';
          modalSubmit.textContent = 'Confirm Archive';
          modalSubmit.className = 'px-4 py-2 rounded-xl text-xs font-semibold text-white bg-amber-600 hover:bg-amber-700 shadow-xs transition';
        }

        modal.classList.remove('hidden');
      });
    });

    if (cancelBtn) {
      cancelBtn.addEventListener('click', function () {
        modal.classList.add('hidden');
      });
    }

    modal.addEventListener('click', function (e) {
      if (e.target === modal) {
        modal.classList.add('hidden');
      }
    });
  }

  // 4. Lesson List (Reorder Announcer & Delete Modal)
  function initLessonList() {
    const urlParams = new URLSearchParams(window.location.search);
    const movedId = urlParams.get('moved');
    if (movedId) {
      const movedEl = document.getElementById('lesson-item-' + movedId);
      if (movedEl) {
        movedEl.focus();
        movedEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
        const announcer = document.getElementById('reorder-announcer');
        if (announcer) {
          const title = movedEl.dataset.lessonTitle || 'Lesson';
          const order = movedEl.dataset.lessonOrder || '';
          announcer.textContent = title + ' moved to position ' + order;
        }
      }
    }

    const deleteModal = document.getElementById('delete-lesson-modal');
    const deleteForm = document.getElementById('delete-lesson-form');
    const deleteCancel = document.getElementById('delete-lesson-modal-cancel');

    if (deleteModal && deleteForm) {
      document.querySelectorAll('.delete-lesson-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
          const title = this.dataset.lessonTitle;
          const deleteUrl = this.dataset.deleteUrl;
          if (deleteUrl) {
            deleteForm.action = deleteUrl;
          }
          const titleEl = document.getElementById('delete-lesson-modal-title');
          if (titleEl) {
            titleEl.textContent = 'Delete Lesson: ' + title;
          }
          deleteModal.classList.remove('hidden');
        });
      });

      if (deleteCancel) {
        deleteCancel.addEventListener('click', function () {
          deleteModal.classList.add('hidden');
        });
      }

      deleteModal.addEventListener('click', function (e) {
        if (e.target === deleteModal) {
          deleteModal.classList.add('hidden');
        }
      });
    }
  }

  // 5. Lesson Form (Video Preview Updater)
  function initLessonForm() {
    const providerSelect = document.getElementById('id_video_provider');
    const videoInput = document.getElementById('id_video_input');
    const previewBox = document.getElementById('video-preview-box');
    const previewIframe = document.getElementById('video-preview-iframe');

    if (!videoInput || !providerSelect || !previewBox || !previewIframe) return;

    function updatePreview() {
      const provider = providerSelect.value;
      const val = videoInput.value.trim();

      if (!val) {
        previewBox.classList.add('hidden');
        previewIframe.src = '';
        return;
      }

      let embedUrl = '';
      if (provider === 'youtube') {
        let videoId = val;
        const ytMatch = val.match(/(?:youtu\.be\/|youtube\.com\/(?:watch\?v=|embed\/|v\/|shorts\/))([\w-]{11})/);
        if (ytMatch) videoId = ytMatch[1];
        if (/^[\w-]{11}$/.test(videoId)) {
          embedUrl = 'https://www.youtube-nocookie.com/embed/' + videoId;
        }
      } else if (provider === 'vimeo') {
        let videoId = val;
        const vimMatch = val.match(/vimeo\.com\/(?:channels\/(?:\w+\/)?|groups\/(?:[^\/]*)\/videos\/|album\/(?:\d+)\/video\/|video\/|)(\d+)/);
        if (vimMatch) videoId = vimMatch[1];
        if (/^\d+$/.test(videoId)) {
          embedUrl = 'https://player.vimeo.com/video/' + videoId;
        }
      }

      if (embedUrl) {
        previewIframe.src = embedUrl;
        previewBox.classList.remove('hidden');
      } else {
        previewBox.classList.add('hidden');
        previewIframe.src = '';
      }
    }

    videoInput.addEventListener('input', updatePreview);
    providerSelect.addEventListener('change', updatePreview);
    updatePreview();
  }

  // 6. Assignment List (Delete Assignment Modal)
  function initAssignmentList() {
    const deleteModal = document.getElementById('delete-assignment-modal');
    const deleteForm = document.getElementById('delete-assignment-form');
    const deleteCancel = document.getElementById('delete-assignment-modal-cancel');

    if (!deleteModal || !deleteForm) return;

    document.querySelectorAll('.delete-assignment-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        const title = this.dataset.assignmentTitle;
        const subCount = parseInt(this.dataset.submissionCount || '0', 10);
        const deleteUrl = this.dataset.deleteUrl;

        if (deleteUrl) {
          deleteForm.action = deleteUrl;
        }
        const titleEl = document.getElementById('delete-assignment-modal-title');
        if (titleEl) {
          titleEl.textContent = 'Delete Assignment: ' + title;
        }

        const descEl = document.getElementById('delete-assignment-modal-desc');
        if (descEl) {
          if (subCount > 0) {
            descEl.innerHTML = '<span class="text-rose-600 dark:text-rose-400 font-bold">Action Blocked:</span> This assignment has ' + subCount + ' submitted response(s). You must unpublish instead of deleting to preserve student grading records.';
          } else {
            descEl.textContent = 'Are you sure you want to delete this empty assignment? This action cannot be undone.';
          }
        }

        deleteModal.classList.remove('hidden');
      });
    });

    if (deleteCancel) {
      deleteCancel.addEventListener('click', function () {
        deleteModal.classList.add('hidden');
      });
    }

    deleteModal.addEventListener('click', function (e) {
      if (e.target === deleteModal) {
        deleteModal.classList.add('hidden');
      }
    });
  }

  // 7. Assignment Form (Unpublish Modal)
  function initAssignmentForm() {
    const form = document.getElementById('assignment-form');
    const isPublishedCheckbox = document.getElementById('id_is_published');
    const confirmUnpublishInput = document.getElementById('id_confirm_unpublish');
    const unpublishModal = document.getElementById('unpublish-modal');
    const unpublishCancel = document.getElementById('unpublish-modal-cancel');
    const unpublishConfirm = document.getElementById('unpublish-modal-confirm');

    if (!form || !isPublishedCheckbox || !unpublishModal) return;

    const originallyPublished = form.getAttribute('data-originally-published') === 'true';
    const submissionCount = parseInt(form.getAttribute('data-submission-count') || '0', 10);

    form.addEventListener('submit', function (e) {
      const willBeUnpublished = originallyPublished && !isPublishedCheckbox.checked;
      const alreadyConfirmed = confirmUnpublishInput && confirmUnpublishInput.value === 'true';

      if (willBeUnpublished && submissionCount > 0 && !alreadyConfirmed) {
        e.preventDefault();
        unpublishModal.classList.remove('hidden');
      }
    });

    if (unpublishCancel) {
      unpublishCancel.addEventListener('click', function () {
        unpublishModal.classList.add('hidden');
        isPublishedCheckbox.checked = true;
      });
    }

    if (unpublishConfirm) {
      unpublishConfirm.addEventListener('click', function () {
        if (confirmUnpublishInput) {
          confirmUnpublishInput.value = 'true';
        }
        unpublishModal.classList.add('hidden');
        form.submit();
      });
    }
  }

  // 8. Material Item Policy Form
  function initMaterialPolicyForm() {
    const policyForm = document.getElementById('policyForm');
    if (!policyForm) return;

    const viewOnlyRadio = document.getElementById('policy_view_only');
    const requestReqRadio = document.getElementById('policy_request_required');
    const viewOnlyWarning = document.getElementById('view_only_warning');
    const keepAccessBox = document.getElementById('keep_access_box');

    function updatePolicyUI() {
      const isViewOnly = viewOnlyRadio ? viewOnlyRadio.checked : false;
      const isRequestReq = requestReqRadio ? requestReqRadio.checked : false;

      if (viewOnlyWarning) {
        viewOnlyWarning.classList.toggle('hidden', !isViewOnly);
      }
      if (keepAccessBox) {
        keepAccessBox.classList.toggle('hidden', !(isViewOnly || isRequestReq));
      }
    }

    document.querySelectorAll('input[name="target_policy"], input[name="download_policy"]').forEach(function (radio) {
      radio.addEventListener('change', updatePolicyUI);
    });

    policyForm.addEventListener('submit', function (e) {
      const isViewOnly = viewOnlyRadio ? viewOnlyRadio.checked : false;
      const currentPolicy = policyForm.getAttribute('data-current-policy') || '';
      const pendingCount = policyForm.getAttribute('data-pending-count') || '0';
      const approvedCount = policyForm.getAttribute('data-approved-count') || '0';

      if (isViewOnly && currentPolicy !== 'view_only') {
        const msg = 'Are you sure you want to switch to View Only?\n\n' +
                    '• ' + pendingCount + ' pending request(s) will be denied.\n' +
                    '• ' + approvedCount + ' approved request(s) will be revoked.\n' +
                    '• Each student will be notified.';
        if (!window.confirm(msg)) {
          e.preventDefault();
        }
      }
    });

    updatePolicyUI();
  }

  // 9. Material Item Form (Item Type Toggling)
  function initMaterialItemForm() {
    const itemTypeSelect = document.getElementById('id_item_type');
    if (!itemTypeSelect) return;

    const fileContainer = document.getElementById('file_fields_container');
    const linkContainer = document.getElementById('link_fields_container');
    const videoContainer = document.getElementById('video_fields_container');

    function toggleItemTypeFields() {
      const itemType = itemTypeSelect.value;
      if (fileContainer) fileContainer.classList.toggle('hidden', itemType !== 'file');
      if (linkContainer) linkContainer.classList.toggle('hidden', itemType !== 'link');
      if (videoContainer) videoContainer.classList.toggle('hidden', itemType !== 'video');
    }

    itemTypeSelect.addEventListener('change', toggleItemTypeFields);
    toggleItemTypeFields();
  }

  // 10. Teacher Permissions Queue
  function initPermissionsQueue() {
    const selectAll = document.getElementById('select-all-checkbox');
    const rowCheckboxes = Array.from(document.querySelectorAll('.row-checkbox'));
    const bulkBar = document.getElementById('bulk-actions-bar');
    const countBadge = document.getElementById('selected-count-badge');
    const bulkCountLabels = document.querySelectorAll('.bulk-count-label');
    const bulkApproveContainer = document.getElementById('bulk-approve-ids-container');
    const bulkDenyContainer = document.getElementById('bulk-deny-ids-container');
    const btnClearSelection = document.getElementById('btn-clear-selection');

    if (!rowCheckboxes.length) return;

    function updateBulkBar() {
      const selected = rowCheckboxes.filter(function (cb) { return cb.checked; });
      const count = selected.length;
      if (count > 0 && bulkBar) {
        bulkBar.classList.remove('hidden');
        if (countBadge) countBadge.textContent = count;
        bulkCountLabels.forEach(function (el) { el.textContent = count; });

        if (bulkApproveContainer && bulkDenyContainer) {
          bulkApproveContainer.innerHTML = '';
          bulkDenyContainer.innerHTML = '';
          selected.forEach(function (cb) {
            const input1 = document.createElement('input');
            input1.type = 'hidden';
            input1.name = 'selected_ids';
            input1.value = cb.value;
            bulkApproveContainer.appendChild(input1);

            const input2 = document.createElement('input');
            input2.type = 'hidden';
            input2.name = 'selected_ids';
            input2.value = cb.value;
            bulkDenyContainer.appendChild(input2);
          });
        }
      } else if (bulkBar) {
        bulkBar.classList.add('hidden');
        if (selectAll) selectAll.checked = false;
      }
    }

    if (selectAll) {
      selectAll.addEventListener('change', function () {
        rowCheckboxes.forEach(function (cb) { cb.checked = selectAll.checked; });
        updateBulkBar();
      });
    }

    rowCheckboxes.forEach(function (cb) {
      cb.addEventListener('change', updateBulkBar);
    });

    if (btnClearSelection) {
      btnClearSelection.addEventListener('click', function () {
        rowCheckboxes.forEach(function (cb) { cb.checked = false; });
        if (selectAll) selectAll.checked = false;
        updateBulkBar();
      });
    }

    // Single Approve Modal Trigger
    document.querySelectorAll('.btn-open-approve').forEach(function (btn) {
      btn.addEventListener('click', function () {
        const reqId = btn.getAttribute('data-request-id');
        const studentName = btn.getAttribute('data-student-name');
        const fileTitle = btn.getAttribute('data-file-title');

        const studentEl = document.getElementById('approve-student-name');
        if (studentEl) studentEl.textContent = studentName;
        const fileEl = document.getElementById('approve-file-title');
        if (fileEl) fileEl.textContent = fileTitle;

        const form = document.getElementById('form-single-approve');
        if (form) form.action = '/dashboard/teacher/permissions/action/' + reqId + '/';

        const modal = document.getElementById('modal-single-approve');
        if (modal) {
          modal.classList.remove('hidden');
          modal.setAttribute('aria-hidden', 'false');
        }
      });
    });

    // Single Deny Modal Trigger
    document.querySelectorAll('.btn-open-deny').forEach(function (btn) {
      btn.addEventListener('click', function () {
        const reqId = btn.getAttribute('data-request-id');
        const studentName = btn.getAttribute('data-student-name');
        const fileTitle = btn.getAttribute('data-file-title');

        const studentEl = document.getElementById('deny-student-name');
        if (studentEl) studentEl.textContent = studentName;
        const fileEl = document.getElementById('deny-file-title');
        if (fileEl) fileEl.textContent = fileTitle;

        const form = document.getElementById('form-single-deny');
        if (form) form.action = '/dashboard/teacher/permissions/action/' + reqId + '/';

        const modal = document.getElementById('modal-single-deny');
        if (modal) {
          modal.classList.remove('hidden');
          modal.setAttribute('aria-hidden', 'false');
        }
      });
    });

    // Approve for All Enrolled Modal Trigger
    document.querySelectorAll('.btn-open-approve-all').forEach(function (btn) {
      btn.addEventListener('click', function () {
        const itemId = btn.getAttribute('data-item-id');
        const itemTitle = btn.getAttribute('data-item-title');

        const itemEl = document.getElementById('approve-all-item-title');
        if (itemEl) itemEl.textContent = itemTitle;

        const form = document.getElementById('form-approve-all');
        if (form) form.action = '/dashboard/teacher/permissions/approve-all/' + itemId + '/';

        const modal = document.getElementById('modal-approve-all');
        if (modal) {
          modal.classList.remove('hidden');
          modal.setAttribute('aria-hidden', 'false');
        }
      });
    });
  }

  // 11. Enrollment List Bulk & Single Actions
  function initEnrollmentList() {
    const checkboxes = Array.from(document.querySelectorAll('.enrollment-checkbox'));
    const bar = document.getElementById('bulk-actions-bar');
    const badge = document.getElementById('selected-count-badge');
    const selectAllCheckbox = document.getElementById('select-all-enrollments') || document.getElementById('select-all-checkbox');

    if (!checkboxes.length && !bar) return;

    function updateSelectionCount() {
      const checked = checkboxes.filter(function (cb) { return cb.checked; });
      if (badge) badge.innerText = checked.length;
      if (bar) {
        if (checked.length > 0) {
          bar.classList.remove('hidden');
          bar.classList.add('flex');
        } else {
          bar.classList.add('hidden');
          bar.classList.remove('flex');
        }
      }
    }

    if (selectAllCheckbox) {
      selectAllCheckbox.addEventListener('change', function () {
        checkboxes.forEach(function (cb) { cb.checked = selectAllCheckbox.checked; });
        updateSelectionCount();
      });
    }

    checkboxes.forEach(function (cb) {
      cb.addEventListener('change', updateSelectionCount);
    });

    // Single Action Triggers
    document.querySelectorAll('[data-single-action]').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        const action = btn.getAttribute('data-single-action');
        const enrollmentId = btn.getAttribute('data-enrollment-id');
        const form = document.getElementById('single-enrollment-form');
        const input = document.getElementById('single-action-input');
        if (form && input && enrollmentId) {
          form.action = '/dashboard/teacher/enrollments/action/' + enrollmentId + '/';
          input.value = action;
          form.submit();
        }
      });
    });

    // Bulk Action Triggers
    document.querySelectorAll('[data-bulk-action]').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        const action = btn.getAttribute('data-bulk-action');
        const checked = checkboxes.filter(function (cb) { return cb.checked; });
        if (checked.length === 0) return;
        if (!window.confirm('Are you sure you want to ' + action + ' ' + checked.length + ' selected enrollment(s)?')) return;

        const form = document.getElementById('bulk-enrollment-form');
        const input = document.getElementById('bulk-action-input');
        if (form && input) {
          input.value = action;
          form.submit();
        }
      });
    });
  }

  // DOM ready hook
  function initAll() {
    initTeacherDrawer();
    initCourseForm();
    initCourseList();
    initLessonList();
    initLessonForm();
    initAssignmentList();
    initAssignmentForm();
    initMaterialPolicyForm();
    initMaterialItemForm();
    initPermissionsQueue();
    initEnrollmentList();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAll);
  } else {
    initAll();
  }
})();
