/**
 * assignments.js - Handles live cosmetic deadline countdowns and upload UX
 * with double-submit protection and bfcache restoration.
 * Zero inline scripts.
 */

(function () {
  "use strict";

  // 1. Server-Anchored Live Cosmetic Countdown
  function initDeadlineCountdowns() {
    var serverTimeContainer = document.querySelector("[data-server-time]");
    if (!serverTimeContainer) return;

    var serverTimeRaw = serverTimeContainer.getAttribute("data-server-time");
    var serverTimestamp = new Date(serverTimeRaw).getTime();
    if (isNaN(serverTimestamp)) return;

    // Calculate clock skew between client device and server
    var clientSkew = Date.now() - serverTimestamp;

    var countdownElements = document.querySelectorAll("[data-countdown-due]");
    if (!countdownElements.length) return;

    function updateCountdowns() {
      var currentSimulatedServerTime = Date.now() - clientSkew;

      countdownElements.forEach(function (el) {
        var dueTimeRaw = el.getAttribute("data-countdown-due");
        var dueTimestamp = new Date(dueTimeRaw).getTime();
        if (isNaN(dueTimestamp)) return;

        var diffMs = dueTimestamp - currentSimulatedServerTime;

        if (diffMs <= 0) {
          el.textContent = "Deadline passed";
          el.classList.add("text-red-600", "dark:text-red-400");
          el.classList.remove("text-indigo-600", "dark:text-indigo-400", "text-emerald-600", "dark:text-emerald-400");
          return;
        }

        var totalSeconds = Math.floor(diffMs / 1000);
        var days = Math.floor(totalSeconds / 86400);
        var hours = Math.floor((totalSeconds % 86400) / 3600);
        var minutes = Math.floor((totalSeconds % 3600) / 60);
        var seconds = totalSeconds % 60;

        var text = "";
        if (days > 0) {
          text = days + "d " + hours + "h " + minutes + "m left";
        } else if (hours > 0) {
          text = hours + "h " + minutes + "m " + seconds + "s left";
        } else {
          text = minutes + "m " + seconds + "s left";
        }

        el.textContent = text;
      });
    }

    updateCountdowns();
    setInterval(updateCountdowns, 1000);
  }

  // 2. Double-Submit Protection and Upload UX (Requirement 14)
  function initSubmissionForm() {
    var form = document.querySelector("form[data-submit-protect]");
    if (!form) return;

    var submitBtn = form.querySelector("#assignment-submit-btn") || form.querySelector("button[type='submit']");
    if (!submitBtn) return;

    var originalBtnHtml = submitBtn.innerHTML;

    form.addEventListener("submit", function () {
      // Allow native HTML5 validation to run first
      if (!form.checkValidity()) return;

      submitBtn.disabled = true;
      submitBtn.setAttribute("aria-busy", "true");

      // Requirement 14: "Uploading, please keep this page open" message
      submitBtn.innerHTML =
        '<svg class="animate-spin -ml-1 mr-2 h-4 w-4 text-white inline-block" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">' +
        '<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>' +
        '<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>' +
        "</svg>" +
        "<span>Uploading, please keep this page open...</span>";
    });

    // Requirement 14: Re-enable the submit button on back/bfcache restore
    window.addEventListener("pageshow", function (event) {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.removeAttribute("aria-busy");
        submitBtn.innerHTML = originalBtnHtml;
      }
    });
  }

  // 3. Client-Side File Chooser UX & Validation (Single file, size limit, type checks)
  function initFileChooser() {
    var fileInput = document.getElementById("file_upload");
    var fileCard = document.getElementById("selected-file-card");
    var filenameEl = document.getElementById("selected-filename");
    var filesizeEl = document.getElementById("selected-filesize");
    var clearBtn = document.getElementById("clear-selected-file-btn");
    var errorBox = document.getElementById("client-file-error");

    if (!fileInput || !fileCard || !filenameEl || !filesizeEl) return;

    var ALLOWED_EXTENSIONS = ["pdf", "docx", "pptx", "txt", "png", "jpg", "jpeg"];
    var MAX_FILE_SIZE = 10 * 1024 * 1024; // 10 MB

    function formatFileSize(bytes) {
      if (bytes < 1024) return bytes + " B";
      var kb = bytes / 1024;
      if (kb < 1024) return kb.toFixed(1) + " KB";
      var mb = kb / 1024;
      return mb.toFixed(1) + " MB";
    }

    function showError(msg) {
      if (errorBox) {
        errorBox.textContent = msg;
        errorBox.classList.remove("hidden");
      }
    }

    function clearError() {
      if (errorBox) {
        errorBox.textContent = "";
        errorBox.classList.add("hidden");
      }
    }

    function resetFile() {
      fileInput.value = "";
      fileCard.classList.add("hidden");
      filenameEl.textContent = "";
      filesizeEl.textContent = "";
      clearError();
    }

    fileInput.addEventListener("change", function () {
      clearError();

      if (!fileInput.files || !fileInput.files.length) {
        resetFile();
        return;
      }

      var file = fileInput.files[0];
      var name = file.name || "";
      var ext = "";
      var dotIdx = name.lastIndexOf(".");
      if (dotIdx !== -1) {
        ext = name.slice(dotIdx + 1).toLowerCase();
      }

      if (file.size > MAX_FILE_SIZE) {
        showError(
          "File exceeds the 10 MB limit (" +
            formatFileSize(file.size) +
            "). Please choose a smaller file."
        );
        resetFile();
        return;
      }

      if (ALLOWED_EXTENSIONS.indexOf(ext) === -1) {
        showError(
          "Unsupported format: ." +
            ext.toUpperCase() +
            ". Allowed formats: PDF, DOCX, PPTX, TXT, PNG, JPG."
        );
        resetFile();
        return;
      }

      filenameEl.textContent = name;
      filesizeEl.textContent = formatFileSize(file.size);
      fileCard.classList.remove("hidden");
    });

    if (clearBtn) {
      clearBtn.addEventListener("click", function () {
        resetFile();
      });
    }
  }

  // DOM Content Loaded Handler
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      initDeadlineCountdowns();
      initSubmissionForm();
      initFileChooser();
    });
  } else {
    initDeadlineCountdowns();
    initSubmissionForm();
    initFileChooser();
  }
})();
