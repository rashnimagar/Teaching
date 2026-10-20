/**
 * Teaching Platform - Accessible Interactive Components Controller
 * Zero external dependencies. All accessible keyboard & ARIA interactions.
 */
(function () {
  'use strict';

  // =========================================================================
  // 1. Accessible Tabs (WAI-ARIA Tab Pattern with Roving Tabindex)
  // =========================================================================
  function initTabs() {
    const tablists = document.querySelectorAll('[data-tablist]');
    tablists.forEach(function (tablist) {
      const tabs = Array.from(tablist.querySelectorAll('[role="tab"]'));
      if (!tabs.length) return;

      function activateTab(tabToActivate, setFocus) {
        tabs.forEach(function (tab) {
          const isSelected = tab === tabToActivate;
          tab.setAttribute('aria-selected', isSelected ? 'true' : 'false');
          tab.setAttribute('tabindex', isSelected ? '0' : '-1');

          // Style active vs inactive tab
          if (isSelected) {
            tab.classList.add('border-indigo-600', 'text-indigo-600', 'dark:text-indigo-400', 'dark:border-indigo-400');
            tab.classList.remove('border-transparent', 'text-slate-600', 'dark:text-slate-400');
          } else {
            tab.classList.remove('border-indigo-600', 'text-indigo-600', 'dark:text-indigo-400', 'dark:border-indigo-400');
            tab.classList.add('border-transparent', 'text-slate-600', 'dark:text-slate-400');
          }

          // Show/Hide controlled panel
          const panelId = tab.getAttribute('aria-controls');
          if (panelId) {
            const panel = document.getElementById(panelId);
            if (panel) {
              if (isSelected) {
                panel.classList.remove('hidden');
                panel.removeAttribute('hidden');
              } else {
                panel.classList.add('hidden');
                panel.setAttribute('hidden', 'until-found');
              }
            }
          }
        });

        if (setFocus) {
          tabToActivate.focus();
        }
      }

      tabs.forEach(function (tab, index) {
        tab.addEventListener('click', function () {
          activateTab(tab, false);
        });

        tab.addEventListener('keydown', function (e) {
          let nextIndex = index;
          if (e.key === 'ArrowRight') {
            nextIndex = (index + 1) % tabs.length;
            e.preventDefault();
          } else if (e.key === 'ArrowLeft') {
            nextIndex = (index - 1 + tabs.length) % tabs.length;
            e.preventDefault();
          } else if (e.key === 'Home') {
            nextIndex = 0;
            e.preventDefault();
          } else if (e.key === 'End') {
            nextIndex = tabs.length - 1;
            e.preventDefault();
          } else {
            return;
          }
          activateTab(tabs[nextIndex], true);
        });
      });
    });
  }

  // =========================================================================
  // 2. Accessible Modals & Drawers (Focus Trap, Escape, Return Focus)
  // =========================================================================
  function initDialogs() {
    let lastActiveElement = null;

    function openDialog(dialog) {
      if (!dialog) return;
      lastActiveElement = document.activeElement;
      dialog.classList.remove('hidden');
      dialog.setAttribute('aria-hidden', 'false');
      document.body.classList.add('overflow-hidden');

      // Find first focusable element or focus container
      const focusable = dialog.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
      if (focusable.length > 0) {
        focusable[0].focus();
      } else {
        dialog.focus();
      }
    }

    function closeDialog(dialog) {
      if (!dialog) return;
      dialog.classList.add('hidden');
      dialog.setAttribute('aria-hidden', 'true');
      document.body.classList.remove('overflow-hidden');

      if (lastActiveElement && typeof lastActiveElement.focus === 'function') {
        lastActiveElement.focus();
        lastActiveElement = null;
      }
    }

    // Bind triggers [data-dialog-trigger="dialog-id"]
    document.querySelectorAll('[data-dialog-trigger]').forEach(function (trigger) {
      trigger.addEventListener('click', function (e) {
        e.preventDefault();
        const dialogId = trigger.getAttribute('data-dialog-trigger');
        const dialog = document.getElementById(dialogId);
        if (dialog) openDialog(dialog);
      });
    });

    // Bind close buttons and backdrop inside dialogs
    document.querySelectorAll('[data-dialog-root]').forEach(function (dialog) {
      dialog.querySelectorAll('[data-dialog-close]').forEach(function (closeBtn) {
        closeBtn.addEventListener('click', function () {
          closeDialog(dialog);
        });
      });

      const backdrop = dialog.querySelector('[data-dialog-backdrop]');
      if (backdrop) {
        backdrop.addEventListener('click', function () {
          closeDialog(dialog);
        });
      }

      // Keyboard Trap: Escape to close, Tab to cycle focus
      dialog.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') {
          e.preventDefault();
          closeDialog(dialog);
          return;
        }

        if (e.key === 'Tab') {
          const focusable = Array.from(dialog.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')).filter(function (el) {
            return !el.disabled && el.offsetParent !== null;
          });
          if (focusable.length === 0) return;

          const first = focusable[0];
          const last = focusable[focusable.length - 1];

          if (e.shiftKey && document.activeElement === first) {
            e.preventDefault();
            last.focus();
          } else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault();
            first.focus();
          }
        }
      });
    });

    // Global helper for opening/closing programmatically
    window.TeachingDialog = {
      open: function (id) {
        openDialog(document.getElementById(id));
      },
      close: function (id) {
        closeDialog(document.getElementById(id));
      }
    };
  }

  // =========================================================================
  // 3. Dismissible Alerts
  // =========================================================================
  function initAlertDismiss() {
    document.querySelectorAll('[data-dismiss="alert"]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        const alertBox = btn.closest('[role="alert"]');
        if (alertBox) {
          alertBox.classList.add('opacity-0', 'scale-95');
          setTimeout(function () {
            alertBox.remove();
          }, 200);
        }
      });
    });
  }

  // =========================================================================
  // 4. Accessible Toast Notifications
  // =========================================================================
  function initToasts() {
    document.querySelectorAll('[data-toast]').forEach(function (toast) {
      const duration = parseInt(toast.getAttribute('data-duration') || '5000', 10);
      let timer = null;

      function startTimer() {
        if (duration > 0) {
          timer = setTimeout(dismiss, duration);
        }
      }

      function pauseTimer() {
        if (timer) clearTimeout(timer);
      }

      function dismiss() {
        toast.classList.add('opacity-0', 'translate-x-full');
        setTimeout(function () {
          toast.remove();
        }, 300);
      }

      const closeBtn = toast.querySelector('[data-toast-dismiss]');
      if (closeBtn) {
        closeBtn.addEventListener('click', dismiss);
      }

      toast.addEventListener('mouseenter', pauseTimer);
      toast.addEventListener('mouseleave', startTimer);

      startTimer();
    });
  }

  // =========================================================================
  // 5. Password Visibility Toggle
  // =========================================================================
  function initPasswordToggles() {
    document.querySelectorAll('[data-toggle-password]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        const targetId = btn.getAttribute('data-toggle-password');
        const input = document.getElementById(targetId);
        if (!input) return;

        const isPassword = input.type === 'password';
        input.type = isPassword ? 'text' : 'password';
        btn.setAttribute('aria-label', isPassword ? 'Hide password' : 'Show password');

        const eyeOpen = btn.querySelector('.icon-eye-open');
        const eyeClosed = btn.querySelector('.icon-eye-closed');
        if (eyeOpen && eyeClosed) {
          eyeOpen.classList.toggle('hidden', isPassword);
          eyeClosed.classList.toggle('hidden', !isPassword);
        }
      });
    });
  }

  // DOM ready hook
  function initAll() {
    initTabs();
    initDialogs();
    initAlertDismiss();
    initToasts();
    initPasswordToggles();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAll);
  } else {
    initAll();
  }
})();
