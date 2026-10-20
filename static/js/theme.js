/**
 * Teaching Platform - Theme Switcher
 * Zero-dependency, CSP-compliant, flash-preventing theme controller.
 */
(function () {
  'use strict';

  // Apply saved or system theme immediately to avoid flash
  function getPreferredTheme() {
    const savedTheme = localStorage.getItem('teaching_theme');
    if (savedTheme === 'dark' || savedTheme === 'light') {
      return savedTheme;
    }
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  const initialTheme = getPreferredTheme();
  if (initialTheme === 'dark') {
    document.documentElement.classList.add('dark');
  } else {
    document.documentElement.classList.remove('dark');
  }

  // Bind interactive toggles once DOM is ready
  function initThemeToggles() {
    const toggles = document.querySelectorAll('[data-theme-toggle]');
    if (!toggles.length) return;

    function syncButtons(isDark) {
      toggles.forEach(function (btn) {
        btn.setAttribute('aria-pressed', isDark ? 'true' : 'false');
        btn.setAttribute('aria-label', isDark ? 'Switch to light mode' : 'Switch to dark mode');
        const sunIcon = btn.querySelector('.theme-icon-sun');
        const moonIcon = btn.querySelector('.theme-icon-moon');
        if (sunIcon && moonIcon) {
          if (isDark) {
            sunIcon.classList.remove('hidden');
            moonIcon.classList.add('hidden');
          } else {
            sunIcon.classList.add('hidden');
            moonIcon.classList.remove('hidden');
          }
        }
      });
    }

    const currentDark = document.documentElement.classList.contains('dark');
    syncButtons(currentDark);

    toggles.forEach(function (btn) {
      btn.addEventListener('click', function () {
        const isNowDark = document.documentElement.classList.toggle('dark');
        localStorage.setItem('teaching_theme', isNowDark ? 'dark' : 'light');
        syncButtons(isNowDark);
      });
    });

    // Listen for system theme changes if user has not explicitly set a manual preference
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function (e) {
      if (!localStorage.getItem('teaching_theme')) {
        if (e.matches) {
          document.documentElement.classList.add('dark');
          syncButtons(true);
        } else {
          document.documentElement.classList.remove('dark');
          syncButtons(false);
        }
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initThemeToggles);
  } else {
    initThemeToggles();
  }
})();
