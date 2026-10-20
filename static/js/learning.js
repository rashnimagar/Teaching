/**
 * Learning Portal Client Interaction Script
 * Handles player.js synchronization, completion toggling, and mobile syllabus drawer.
 */
document.addEventListener("DOMContentLoaded", () => {
  const container = document.getElementById("learning-container");
  if (!container) return;

  const csrfToken = container.dataset.csrfToken || "";
  const toggleUrl = container.dataset.toggleUrl || "";
  const positionUrl = container.dataset.positionUrl || "";
  const initialPosition = parseInt(container.dataset.lastPosition || "0", 10);
  const provider = (container.dataset.provider || "").toLowerCase();

  let lastTrackedTime = initialPosition;
  let lastSavedTime = initialPosition;
  let isSavingPosition = false;

  // --------------------------------------------------------------------------
  // 1. Video Player Position Tracking (Bunny Stream & Vimeo via player.js)
  // --------------------------------------------------------------------------
  const videoIframe = document.getElementById("lesson-video-iframe");

  if (videoIframe && (provider === "bunny" || provider === "vimeo") && typeof window.playerjs !== "undefined") {
    try {
      const player = new window.playerjs.Player(videoIframe);

      player.on("ready", () => {
        // Resume from last position if available
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

  // Periodic position save via fetch
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

  // Save playback position periodically (every 15 seconds if progressed)
  const syncInterval = setInterval(() => {
    if (Math.abs(lastTrackedTime - lastSavedTime) >= 3) {
      savePositionFetch(lastTrackedTime);
    }
  }, 15000);

  // Save on page exit using sendBeacon with FormData (csrfmiddlewaretoken)
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
  // 2. Mark as Complete / Incomplete Toggle
  // --------------------------------------------------------------------------
  const toggleBtn = document.getElementById("toggle-complete-btn");
  if (toggleBtn && toggleUrl) {
    toggleBtn.addEventListener("click", async (e) => {
      e.preventDefault();
      toggleBtn.disabled = true;

      try {
        const response = await fetch(toggleUrl, {
          method: "POST",
          headers: {
            "X-CSRFToken": csrfToken,
            "X-Requested-With": "XMLHttpRequest",
          },
        });

        if (response.ok) {
          const data = await response.json();
          const isCompleted = data.completed;

          // Update toggle button text and classes
          const btnText = document.getElementById("toggle-btn-text");
          const btnIcon = document.getElementById("toggle-btn-icon");

          if (isCompleted) {
            if (btnText) btnText.textContent = "Completed";
            toggleBtn.classList.remove("bg-white", "dark:bg-gray-800", "text-gray-700", "dark:text-gray-200", "border-gray-300", "dark:border-gray-700");
            toggleBtn.classList.add("bg-emerald-600", "text-white", "border-emerald-600", "hover:bg-emerald-700");
            if (btnIcon) {
              btnIcon.innerHTML = `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7" />`;
            }
          } else {
            if (btnText) btnText.textContent = "Mark as Complete";
            toggleBtn.classList.remove("bg-emerald-600", "text-white", "border-emerald-600", "hover:bg-emerald-700");
            toggleBtn.classList.add("bg-white", "dark:bg-gray-800", "text-gray-700", "dark:text-gray-200", "border-gray-300", "dark:border-gray-700");
            if (btnIcon) {
              btnIcon.innerHTML = `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />`;
            }
          }

          // Update active lesson tick in sidebar
          const activeSidebarIcon = document.querySelector(`.sidebar-lesson-item[data-current="true"] .lesson-status-icon`);
          if (activeSidebarIcon) {
            if (isCompleted) {
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

          // Update progress percentages across the page
          const progressPercentEls = document.querySelectorAll(".course-progress-percent");
          progressPercentEls.forEach((el) => {
            el.textContent = `${data.progress_percentage}%`;
          });

          const progressBarEls = document.querySelectorAll(".course-progress-bar");
          progressBarEls.forEach((bar) => {
            bar.style.width = `${data.progress_percentage}%`;
          });

          const progressCountEls = document.querySelectorAll(".course-completed-count");
          progressCountEls.forEach((el) => {
            el.textContent = data.completed_count.toString();
          });
        }
      } catch (err) {
        console.error("Toggle complete failed:", err);
      } finally {
        toggleBtn.disabled = false;
      }
    });
  }

  // --------------------------------------------------------------------------
  // 3. Mobile Sidebar Drawer Controls
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
