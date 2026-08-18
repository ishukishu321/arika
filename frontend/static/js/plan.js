/* plan.js — the Task Plan (Todo List) widget. Polls /api/plan every couple
 * seconds while the window is open (or while a plan is in_progress) and
 * renders Arika's step-by-step to-do list, same shape as agent_planner.py's
 * summary(): {has_plan, goal, status, steps: [{index, text, status,
 * result, error}], ...} */

const ArikaPlan = (() => {
  let win, closeBtn, goalEl, bodyEl, emptyEl, cancelBtn, openBtn;
  let pollTimer = null;
  let isOpen = false;

  const STEP_ICON = {
    pending: "○",
    in_progress: "◐",
    done: "✔",
    failed: "✖",
    needs_input: "◉",
    skipped: "–",
  };

  function _renderSteps(plan) {
    if (!plan || !plan.has_plan) {
      emptyEl.style.display = "block";
      bodyEl.innerHTML = "";
      bodyEl.appendChild(emptyEl);
      goalEl.textContent = "";
      cancelBtn.style.display = "none";
      return;
    }

    emptyEl.style.display = "none";
    goalEl.textContent = `Goal: ${plan.goal}`;
    cancelBtn.style.display = plan.status === "in_progress" ? "block" : "none";

    bodyEl.innerHTML = "";
    (plan.steps || []).forEach((step) => {
      const row = document.createElement("div");
      row.className = `plan-step ${step.status}`;

      const icon = document.createElement("span");
      icon.className = "plan-step-icon";
      icon.textContent = STEP_ICON[step.status] || "○";

      const textWrap = document.createElement("div");
      const text = document.createElement("div");
      text.className = "plan-step-text";
      text.textContent = `${step.index + 1}. ${step.text}`;
      textWrap.appendChild(text);

      const note = step.error || step.result;
      if (note && (step.status === "failed" || step.status === "needs_input")) {
        const noteEl = document.createElement("div");
        noteEl.className = "plan-step-note";
        noteEl.textContent = note;
        textWrap.appendChild(noteEl);
      }

      row.appendChild(icon);
      row.appendChild(textWrap);
      bodyEl.appendChild(row);
    });
  }

  async function refresh() {
    try {
      const res = await fetch("/api/plan");
      const plan = await res.json();
      _renderSteps(plan);
      return plan;
    } catch (e) {
      console.warn("[plan] failed to load", e);
      return null;
    }
  }

  function _startPolling() {
    if (pollTimer) return;
    pollTimer = setInterval(async () => {
      const plan = await refresh();
      // Auto-stop polling once the plan is finished/cancelled and the
      // widget is closed, so we're not hammering the server forever.
      if (!isOpen && (!plan || !plan.has_plan || plan.status !== "in_progress")) {
        _stopPolling();
      }
    }, 2500);
  }

  function _stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function open() {
    isOpen = true;
    win.classList.add("show");
    refresh();
    _startPolling();
  }

  function close() {
    isOpen = false;
    win.classList.remove("show");
  }

  async function cancelPlan() {
    if (!confirm("Cancel the current plan? Arika will stop working on it.")) return;
    await fetch("/api/plan/cancel", { method: "POST" });
    refresh();
  }

  function init() {
    win = document.getElementById("plan-window");
    closeBtn = document.getElementById("plan-close");
    goalEl = document.getElementById("plan-goal");
    bodyEl = document.getElementById("plan-body");
    emptyEl = document.getElementById("plan-empty");
    cancelBtn = document.getElementById("plan-cancel-btn");
    openBtn = document.getElementById("plan-open-btn");

    if (!win) return;

    openBtn.addEventListener("click", open);
    closeBtn.addEventListener("click", close);
    cancelBtn.addEventListener("click", cancelPlan);

    // --- MOVABLE WINDOW (same drag pattern as the tic-tac-toe window) ---
    const header = document.getElementById("plan-header");
    let isDragging = false, startX, startY, initialX, initialY;

    function startDrag(e) {
      isDragging = true;
      const clientX = e.type.includes("mouse") ? e.clientX : e.touches[0].clientX;
      const clientY = e.type.includes("mouse") ? e.clientY : e.touches[0].clientY;
      startX = clientX;
      startY = clientY;
      initialX = win.offsetLeft;
      initialY = win.offsetTop;
      win.style.right = "auto";
    }

    function doDrag(e) {
      if (!isDragging) return;
      e.preventDefault();
      const clientX = e.type.includes("mouse") ? e.clientX : e.touches[0].clientX;
      const clientY = e.type.includes("mouse") ? e.clientY : e.touches[0].clientY;
      win.style.left = initialX + clientX - startX + "px";
      win.style.top = initialY + clientY - startY + "px";
    }

    function stopDrag() { isDragging = false; }

    header.addEventListener("mousedown", startDrag);
    document.addEventListener("mousemove", doDrag);
    document.addEventListener("mouseup", stopDrag);
    header.addEventListener("touchstart", startDrag, { passive: false });
    document.addEventListener("touchmove", doDrag, { passive: false });
    document.addEventListener("touchend", stopDrag);

    // Light background poll even while closed, just so a badge/notification
    // could be added later if a plan is quietly running. Cheap: only every
    // 6s, and only actually re-renders if the widget is open.
    refresh().then((plan) => {
      if (plan && plan.has_plan && plan.status === "in_progress") {
        _startPolling();
      }
    });
  }

  return { init, open, close, refresh };
})();

document.addEventListener("DOMContentLoaded", () => {
  ArikaPlan.init();
  window.ArikaPlan = ArikaPlan;
});
