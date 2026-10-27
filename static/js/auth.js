/**
 * Teaching Platform - Authentication Pages Static Controller
 * Handles accessible error focus and live password strength indicator.
 * Zero inline scripts.
 */
(function () {
  'use strict';

  function initAuthHelpers() {
    // 1. Move focus to error summary upon failed submit (WCAG accessibility)
    const errorSummary = document.getElementById('error-summary');
    if (errorSummary) {
      errorSummary.focus();
    }

    // 2. Compact live password strength hint on signup
    const pwd1 = document.getElementById('id_password1');
    const indicator = document.getElementById('pwd-length-indicator');
    const hintText = document.getElementById('pwd-hint-text');

    if (pwd1 && indicator && hintText) {
      pwd1.addEventListener('input', function () {
        const len = pwd1.value.length;
        if (len === 0) {
          indicator.className = 'inline-block w-1.5 h-1.5 rounded-full bg-slate-300 dark:bg-slate-600 transition-colors';
          hintText.textContent = 'Minimum 10 characters';
        } else if (len < 10) {
          indicator.className = 'inline-block w-1.5 h-1.5 rounded-full bg-amber-500 transition-colors';
          hintText.textContent = len + '/10 characters (too short)';
        } else if (len < 16) {
          indicator.className = 'inline-block w-1.5 h-1.5 rounded-full bg-emerald-500 transition-colors';
          hintText.textContent = 'Good password length!';
        } else {
          indicator.className = 'inline-block w-1.5 h-1.5 rounded-full bg-indigo-500 transition-colors';
          hintText.textContent = 'Strong passphrase!';
        }
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAuthHelpers);
  } else {
    initAuthHelpers();
  }
})();
