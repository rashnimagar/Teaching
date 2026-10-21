/**
 * Learning Portal Client Interaction Script
 * Handles:
 * 1. Click-to-load YouTube facade (materially improving Lighthouse scores).
 * 2. Player.js synchronization for Bunny/Vimeo.
 * 3. Optimistic Mark Complete UI with loading state, rollback, and error toast.
 * 4. Accessible Tab Switching for Lesson Notes & Assignments.
 * 5. Mobile Syllabus Drawer Controls.
 */
document.addEventListener("DOMContentLoaded", () => {
  const container = document.getElementById("learning-container");
  if (!container) return;

  const csrfToken = container.dataset.csrfToken || "";
  const toggleUrl = container.dataset.toggleUrl || "";
  const positionUrl = container.dataset.positionUrl || "";
  const initialPosition = parseInt(container.dataset.lastPosition || "0", 10);
  const provider = (container.dataset.provider || "").toLowerCase();

  // --------------------------------------------------------------------------
  // 1. Click-to-Load Facade for YouTube (Boosts Lighthouse Performance)
  // --------------------------------------------------------------------------
  const youtubeFacade = document.getElementById("youtube-facade");
  const theaterFrame = document.getElementById("video-theater-frame");

  function loadYouTubeVideo() {
    if (!youtubeFacade || !theaterFrame) return;

    const embedUrl = youtubeFacade.dataset.embedUrl || "";
    const videoTitle = youtubeFacade.dataset.videoTitle || "Lesson Video";
    if (!embedUrl) return;

    const autoplayUrl = embedUrl.includes("?") ? `${embedUrl}&autoplay=1` : `${embedUrl}?autoplay=1`;

    const iframe = document.createElement("iframe");
    iframe.id = "lesson-video-iframe";
    iframe.src = autoplayUrl;
    iframe.title = videoTitle;
    iframe.className = "w-full h-full border-0";
    iframe.allow = "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share";
    iframe.allowFullscreen = true;
    iframe.referrerPolicy = "strict-origin-when-cross-origin";
    iframe.sandbox = "allow-scripts allow-same-origin allow-presentation allow-popups allow-popups-to-escape-sandbox";

    theaterFrame.innerHTML = "";
    theaterFrame.appendChild(iframe);
    iframe.focus();
  }

  if (youtubeFacade) {
    youtubeFacade.addEventListener("click", loadYouTubeVideo);
    youtubeFacade.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        loadYouTubeVideo();
      }
    });
  }

  // --------------------------------------------------------------------------
  // 2. Video Player Position Tracking (Bunny Stream & Vimeo via player.js)
  // --------------------------------------------------------------------------
  let lastTrackedTime = initialPosition;
  let lastSavedTime = initialPosition;
  let isSavingPosition = false;

  const existingIframe = document.getElementById("lesson-video-iframe");
  if (existingIframe && (provider === "bunny" || provider === "vimeo") && typeof window.playerjs !== "undefined") {
    try {
      const player = new window.playerjs.Player(existingIframe);

      player.on("ready", () => {
        if (initialPosition > 0) {
          try {
            player.setCurrentTime(initialPosition);
          } catch (e) {
            console.debug("Unable to set initial playback time:", e);
          }
        }
      });

      player.on("timeupdate", (data) => {
        if (data && typeof data.seconds === "number") {
          lastTrackedTime = Math.floor(data.seconds);
        }
      });
    } catch (err) {
      console.warn("player.js initialization skipped:", err);
    }
  }

  function savePositionFetch(position) {
    if (!positionUrl || position <= 0 || position === lastSavedTime || isSavingPosition) return;

    isSavingPosition = true;
    const body = new URLSearchParams();
    body.append("position", position.toString());

    fetch(positionUrl, {
      method: "POST",
      headers: {
        "X-CSRFToken": csrfToken,
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Requested-With": "XMLHttpRequest",
      },
      body: body.toString(),
    })
      .then((res) => {
        if (res.ok) {
          lastSavedTime = position;
        }
      })
      .catch((err) => console.debug("Position save failed:", err))
      .finally(() => {
        isSavingPosition = false;
      });
  }

  setInterval(() => {
    if (Math.abs(lastTrackedTime - lastSavedTime) >= 3) {
      savePositionFetch(lastTrackedTime);
    }
  }, 15000);

  function savePositionBeacon() {
    if (!positionUrl || lastTrackedTime <= 0 || lastTrackedTime === lastSavedTime) return;

    if (navigator.sendBeacon) {
      const formData = new FormData();
      formData.append("csrfmiddlewaretoken", csrfToken);
      formData.append("position", lastTrackedTime.toString());
      navigator.sendBeacon(positionUrl, formData);
      lastSavedTime = lastTrackedTime;
    } else {
      savePositionFetch(lastTrackedTime);
    }
  }

  window.addEventListener("pagehide", savePositionBeacon);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      savePositionBeacon();
    }
  });

  // --------------------------------------------------------------------------
  // 3. Toast Notifications for Offline / 429 / Error Handling
  // --------------------------------------------------------------------------
  const toastContainer = document.getElementById("toast-container");

  function showToast(message, type = "error") {
    if (!toastContainer) return;

    const toast = document.createElement("div");
    toast.className = `p-4 rounded-2xl shadow-xl border text-sm font-medium flex items-center gap-3 transition-all transform duration-300 pointer-events-auto ${
      type === "error"
        ? "bg-red-50 dark:bg-red-950/90 text-red-800 dark:text-red-200 border-red-200 dark:border-red-800"
        : "bg-emerald-50 dark:bg-emerald-950/90 text-emerald-800 dark:text-emerald-200 border-emerald-200 dark:border-emerald-800"
    }`;
    toast.setAttribute("role", "alert");

    const iconSvg =
      type === "error"
        ? `<svg class="w-5 h-5 text-red-600 dark:text-red-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/></svg>`
        : `<svg class="w-5 h-5 text-emerald-600 dark:text-emerald-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>`;

    toast.innerHTML = `
      ${iconSvg}
      <span class="flex-1">${message}</span>
      <button type="button" class="p-1 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 focus:outline-none" aria-label="Close notification">
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
      </button>
    `;

    const closeBtn = toast.querySelector("button");
    if (closeBtn) {
      closeBtn.addEventListener("click", () => {
        toast.remove();
      });
    }

    toastContainer.appendChild(toast);

    setTimeout(() => {
      if (toast.parentElement) {
        toast.classList.add("opacity-0", "translate-y-2");
        setTimeout(() => toast.remove(), 300);
      }
    }, 4500);
  }

  // --------------------------------------------------------------------------
  // 4. Mark as Complete Toggle: Optimistic UI with Rollback & Loading Spinner
  // --------------------------------------------------------------------------
  const toggleBtn = document.getElementById("toggle-complete-btn");
  const toggleBtnText = document.getElementById("toggle-btn-text");
  const toggleBtnIcon = document.getElementById("toggle-btn-icon");
  const toggleBtnSpinner = document.getElementById("toggle-btn-spinner");

  let isCurrentCompleted = toggleBtn ? toggleBtn.classList.contains("bg-emerald-600") : false;

  function renderButtonState(completed, isLoading = false) {
    if (!toggleBtn) return;

    if (isLoading) {
      if (toggleBtnSpinner) toggleBtnSpinner.classList.remove("hidden");
      if (toggleBtnIcon) toggleBtnIcon.classList.add("hidden");
    } else {
      if (toggleBtnSpinner) toggleBtnSpinner.classList.add("hidden");
      if (toggleBtnIcon) toggleBtnIcon.classList.remove("hidden");
    }

    if (completed) {
      if (toggleBtnText) toggleBtnText.textContent = "Completed";
      toggleBtn.classList.remove(
        "bg-white",
        "dark:bg-gray-800",
        "text-gray-700",
        "dark:text-gray-200",
        "border-gray-300",
        "dark:border-gray-700",
        "hover:bg-gray-50",
        "dark:hover:bg-gray-750"
      );
      toggleBtn.classList.add("bg-emerald-600", "text-white", "border-emerald-600", "hover:bg-emerald-700");
      if (toggleBtnIcon) {
        toggleBtnIcon.innerHTML = `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7" />`;
      }
    } else {
      if (toggleBtnText) toggleBtnText.textContent = "Mark as Complete";
      toggleBtn.classList.remove("bg-emerald-600", "text-white", "border-emerald-600", "hover:bg-emerald-700");
      toggleBtn.classList.add(
        "bg-white",
        "dark:bg-gray-800",
        "text-gray-700",
        "dark:text-gray-200",
        "border-gray-300",
        "dark:border-gray-700",
        "hover:bg-gray-50",
        "dark:hover:bg-gray-750"
      );
      if (toggleBtnIcon) {
        toggleBtnIcon.innerHTML = `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />`;
      }
    }
  }

  function updateSidebarItemIcon(completed) {
    const activeSidebarIcon = document.querySelector(
      `.sidebar-lesson-item[data-current="true"] .lesson-status-icon`
    );
    if (!activeSidebarIcon) return;

    if (completed) {
      activeSidebarIcon.innerHTML = `
        <span class="w-5 h-5 rounded-full bg-emerald-500/20 text-emerald-600 dark:text-emerald-400 flex items-center justify-center">
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"/></svg>
        </span>
      `;
    } else {
      activeSidebarIcon.innerHTML = `
        <span class="w-5 h-5 rounded-full border-2 border-indigo-500 flex items-center justify-center">
          <span class="w-1.5 h-1.5 rounded-full bg-indigo-500"></span>
        </span>
      `;
    }
  }

  function updateProgressMetrics(percent, count) {
    document.querySelectorAll(".course-progress-percent").forEach((el) => {
      el.textContent = `${percent}%`;
    });
    document.querySelectorAll(".course-progress-bar").forEach((bar) => {
      bar.style.width = `${percent}%`;
    });
    if (typeof count === "number") {
      document.querySelectorAll(".course-completed-count").forEach((el) => {
        el.textContent = count.toString();
      });
    }
  }

  if (toggleBtn && toggleUrl) {
    toggleBtn.addEventListener("click", async (e) => {
      e.preventDefault();

      if (!navigator.onLine) {
        showToast("You appear to be offline. Please connect to the internet to update your progress.");
        return;
      }

      // 1. Snapshot previous state for rollback
      const prevCompleted = isCurrentCompleted;
      const countEl = document.querySelector(".course-completed-count");
      const prevCount = countEl ? parseInt(countEl.textContent || "0", 10) : 0;
      const percentEl = document.querySelector(".course-progress-percent");
      const prevPercent = percentEl ? parseInt(percentEl.textContent || "0", 10) : 0;

      // 2. Optimistic UI update
      const optimisticCompleted = !prevCompleted;
      isCurrentCompleted = optimisticCompleted;
      renderButtonState(optimisticCompleted, true);
      updateSidebarItemIcon(optimisticCompleted);

      // Estimated progress count & percentage for instantaneous response
      const totalLessonsEl = document.querySelector(".course-completed-count");
      const optimisticCount = Math.max(0, prevCount + (optimisticCompleted ? 1 : -1));
      updateProgressMetrics(prevPercent, optimisticCount);

      try {
        const response = await fetch(toggleUrl, {
          method: "POST",
          headers: {
            "X-CSRFToken": csrfToken,
            "X-Requested-With": "XMLHttpRequest",
          },
        });

        if (!response.ok) {
          if (response.status === 429) {
            throw new Error("429");
          }
          throw new Error(`Server returned ${response.status}`);
        }

        const data = await response.json();
        // Authoritative server state
        isCurrentCompleted = data.completed;
        renderButtonState(data.completed, false);
        updateSidebarItemIcon(data.completed);
        updateProgressMetrics(data.progress_percentage, data.completed_count);
      } catch (err) {
        // Rollback on error
        console.warn("Toggle complete failed, rolling back:", err);
        isCurrentCompleted = prevCompleted;
        renderButtonState(prevCompleted, false);
        updateSidebarItemIcon(prevCompleted);
        updateProgressMetrics(prevPercent, prevCount);

        if (err.message === "429") {
          showToast("Too many requests. Please wait a moment before trying again.");
        } else {
          showToast("Unable to save progress. Please try again.");
        }
      }
    });
  }

  // --------------------------------------------------------------------------
  // 5. Tabs Controller (Lesson Notes & Course Assignments)
  // --------------------------------------------------------------------------
  const tabNotesBtn = document.getElementById("tab-notes-btn");
  const tabAssignmentsBtn = document.getElementById("tab-assignments-btn");
  const panelNotes = document.getElementById("panel-notes");
  const panelAssignments = document.getElementById("panel-assignments");

  function switchTab(target) {
    if (target === "notes") {
      if (tabNotesBtn) {
        tabNotesBtn.setAttribute("aria-selected", "true");
        tabNotesBtn.classList.remove("border-transparent", "text-gray-500", "dark:text-gray-400");
        tabNotesBtn.classList.add("border-indigo-600", "text-indigo-600", "dark:text-indigo-400");
      }
      if (tabAssignmentsBtn) {
        tabAssignmentsBtn.setAttribute("aria-selected", "false");
        tabAssignmentsBtn.classList.remove("border-indigo-600", "text-indigo-600", "dark:text-indigo-400");
        tabAssignmentsBtn.classList.add("border-transparent", "text-gray-500", "dark:text-gray-400");
      }
      if (panelNotes) panelNotes.classList.remove("hidden");
      if (panelAssignments) panelAssignments.classList.add("hidden");
    } else {
      if (tabAssignmentsBtn) {
        tabAssignmentsBtn.setAttribute("aria-selected", "true");
        tabAssignmentsBtn.classList.remove("border-transparent", "text-gray-500", "dark:text-gray-400");
        tabAssignmentsBtn.classList.add("border-indigo-600", "text-indigo-600", "dark:text-indigo-400");
      }
      if (tabNotesBtn) {
        tabNotesBtn.setAttribute("aria-selected", "false");
        tabNotesBtn.classList.remove("border-indigo-600", "text-indigo-600", "dark:text-indigo-400");
        tabNotesBtn.classList.add("border-transparent", "text-gray-500", "dark:text-gray-400");
      }
      if (panelAssignments) panelAssignments.classList.remove("hidden");
      if (panelNotes) panelNotes.classList.add("hidden");
    }
  }

  if (tabNotesBtn) {
    tabNotesBtn.addEventListener("click", () => switchTab("notes"));
  }
  if (tabAssignmentsBtn) {
    tabAssignmentsBtn.addEventListener("click", () => switchTab("assignments"));
  }

  // Keyboard navigation between tabs
  const tablist = document.querySelector('[role="tablist"]');
  if (tablist) {
    tablist.addEventListener("keydown", (e) => {
      if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
        e.preventDefault();
        const activeTab = document.querySelector('.tab-btn[aria-selected="true"]');
        if (activeTab === tabNotesBtn && tabAssignmentsBtn) {
          tabAssignmentsBtn.focus();
          switchTab("assignments");
        } else if (activeTab === tabAssignmentsBtn && tabNotesBtn) {
          tabNotesBtn.focus();
          switchTab("notes");
        }
      }
    });
  }

  // --------------------------------------------------------------------------
  // 6. Mobile Sidebar Drawer Controls
  // --------------------------------------------------------------------------
  const drawer = document.getElementById("mobile-syllabus-drawer");
  const openDrawerBtn = document.getElementById("open-syllabus-drawer-btn");
  const closeDrawerBtn = document.getElementById("close-syllabus-drawer-btn");
  const drawerBackdrop = document.getElementById("drawer-backdrop");

  function openDrawer() {
    if (!drawer) return;
    drawer.classList.remove("hidden");
    document.body.classList.add("overflow-hidden");
    if (openDrawerBtn) openDrawerBtn.setAttribute("aria-expanded", "true");
  }

  function closeDrawer() {
    if (!drawer) return;
    drawer.classList.add("hidden");
    document.body.classList.remove("overflow-hidden");
    if (openDrawerBtn) openDrawerBtn.setAttribute("aria-expanded", "false");
  }

  if (openDrawerBtn) openDrawerBtn.addEventListener("click", openDrawer);
  if (closeDrawerBtn) closeDrawerBtn.addEventListener("click", closeDrawer);
  if (drawerBackdrop) drawerBackdrop.addEventListener("click", closeDrawer);

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && drawer && !drawer.classList.contains("hidden")) {
      closeDrawer();
    }
  });
});
