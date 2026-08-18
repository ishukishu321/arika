/* chat.js — glues the chat window, sidebar sessions, and the stt/tts modules together. */

document.addEventListener("DOMContentLoaded", () => {
  const chatWindow = document.getElementById("chat-window");
  const userInput = document.getElementById("user_input");
  const liveBtn = document.getElementById("live-btn");
  const historyList = document.getElementById("history-list");
  const viewingBanner = document.getElementById("viewing-old-banner");
  const backToCurrentBtn = document.getElementById("back-to-current-btn");
  const resumeSessionBtn = document.getElementById("resume-session-btn");
  const chatTitle = document.getElementById("chat-title");
  const sendBtn = document.getElementById("send-btn");

  let activeSessionId = null;   // the session new messages actually go to
  let viewingSessionId = null;  // the session currently rendered (may be a past, read-only one)
  let selectedImageFile = null; // File currently attached, waiting to be sent

  const attachBtn = document.getElementById("attach-btn");
  const imageInput = document.getElementById("image-input");
  const imagePreviewRow = document.getElementById("image-preview-row");
  const imagePreviewThumb = document.getElementById("image-preview-thumb");
  const imagePreviewRemove = document.getElementById("image-preview-remove");

  chatWindow.scrollTop = chatWindow.scrollHeight;

  // Recent-history text may carry an "[image]<url> caption" marker (see
  // backend/app.py) so past chats still show the picture on reopen.
  const IMAGE_MARKER_RE = /^\[image\](\S+)(?:\s+([\s\S]*))?$/;

  function appendMessage(sender, text) {
    const div = document.createElement("div");
    div.className = `msg ${sender === "You" ? "user" : "arika"}`;

    const match = typeof text === "string" ? text.match(IMAGE_MARKER_RE) : null;
    if (match) {
      const img = document.createElement("img");
      img.className = "chat-image";
      img.src = match[1];
      div.appendChild(img);
      if (match[2]) {
        const caption = document.createElement("div");
        caption.innerText = match[2];
        div.appendChild(caption);
      }
    } else {
      div.innerText = text;
    }

    chatWindow.appendChild(div);
    chatWindow.scrollTop = chatWindow.scrollHeight;
    return div;
  }

  function clearSelectedImage() {
    selectedImageFile = null;
    imageInput.value = "";
    imagePreviewRow.classList.remove("show");
    imagePreviewThumb.src = "";
  }

  attachBtn.addEventListener("click", () => imageInput.click());

  imageInput.addEventListener("change", () => {
    const file = imageInput.files && imageInput.files[0];
    if (!file) return;
    selectedImageFile = file;
    const reader = new FileReader();
    reader.onload = () => {
      imagePreviewThumb.src = reader.result;
      imagePreviewRow.classList.add("show");
    };
    reader.readAsDataURL(file);
  });

  imagePreviewRemove.addEventListener("click", clearSelectedImage);

  function setReadOnlyMode(isReadOnly) {
    viewingBanner.classList.toggle("show", isReadOnly);
    userInput.disabled = isReadOnly;
    sendBtn.disabled = isReadOnly;
    userInput.placeholder = isReadOnly ? "Read-only — go back to current chat to reply" : "type here.......";
  }

  Tts.setOnQueueEmpty(() => Stt.resumeIfActive());

  // --- Emotion detection: cheap keyword heuristic on Arika's own reply text,
  // driving Avatar.setEmotion() so her face actually reacts instead of
  // staying neutral the whole conversation. This is intentionally simple
  // (no extra API round-trip) — good enough to read as "alive", not meant
  // to be a real sentiment model.
  function detectEmotion(text) {
    const t = text.toLowerCase();
    if (/(sorry|unfortunately|i feel bad|that'?s sad|miss(ing)? (you|him|her)|:\()/.test(t)) return 'sad';
    if (/(ugh|seriously\?|so annoying|that'?s stupid|hmph|i'?m not mad|angry)/.test(t)) return 'angry';
    if (/(wow|omg|no way|what\?!|really\?!|can'?t believe|surprising|shocked)/.test(t)) return 'surprised';
    if (/(haha|lol|😂|😆|great job|nice one|awesome|yay|glad|happy|good job|love that)/.test(t)) return 'happy';
    if (/!/.test(t)) return 'happy';
    return 'neutral';
  }

  function reactToReply(text) {
    if (window.Avatar && typeof Avatar.setEmotion === 'function') {
      Avatar.setEmotion(detectEmotion(text));
    }
  }

  async function handleSend(textOverride = null) {
    if (viewingSessionId && viewingSessionId !== activeSessionId) return; // read-only guard
    const text = textOverride || userInput.value.trim();
    const imageFile = textOverride ? null : selectedImageFile;
    if (!text && !imageFile) return;

    if (!textOverride) userInput.value = "";

    // Show the user's own message right away, image included.
    if (imageFile) {
      const localUrl = imagePreviewThumb.src; // already a data: URL from the preview
      appendMessage("You", `[image]${localUrl}${text ? " " + text : ""}`);
    } else {
      appendMessage("You", text);
    }
    clearSelectedImage();

    const typingDiv = appendMessage("Arika", "Typing...");
    typingDiv.id = "typing";

    try {
      let response;
      if (imageFile) {
        const formData = new FormData();
        formData.append("user_message", text);
        formData.append("image", imageFile);
        response = await fetch("/api/chat", { method: "POST", body: formData });
      } else {
        response = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ user_message: text }),
        });
      }
      const data = await response.json();

      if (!response.ok && data.error === "missing_api_key") {
        typingDiv.remove();
        appendMessage("Arika", "I need a Gemini API key first — open Settings to add one.");
        if (window.ArikaSettings) window.ArikaSettings.open();
        Stt.resumeIfActive();
        return;
      }

      typingDiv.remove();
      appendMessage("Arika", data.response);
      reactToReply(data.response);
      refreshSessionsSidebar();

      if (data.audio_urls && data.audio_urls.length > 0) {
        Tts.enqueue(data.audio_urls);
      } else {
        Stt.resumeIfActive();
      }
    } catch (error) {
      typingDiv.innerText = "Error connecting to server.";
      console.error(error);
      Stt.resumeIfActive();
    }
  }

  // Image sending is disabled.

  // --- Proactive Minecraft awareness polling -------------------------
  // Backend checks bot events every ~15s (see backend/minecraft_manager.py
  // + minecraft_awareness.py) and only ever queues a message when something
  // is genuinely notable. To avoid hammering the server with a request
  // every 5s even when Minecraft mode is completely off, we first check the
  // (cheap) mode flag every 20s, and only run the frequent 5s awareness
  // poll while that flag says mode is actually active.
  let minecraftModeActive = false;

  async function refreshMinecraftModeFlag() {
    try {
      const response = await fetch("/api/minecraft/status");
      if (!response.ok) return;
      const data = await response.json();
      minecraftModeActive = !!data.minecraft_mode;
    } catch (error) {
      // Silent — background convenience check, not a user action.
    }
  }

  async function pollMinecraftAwareness() {
    if (!minecraftModeActive) return; // mode is off — nothing to check
    if (viewingSessionId && viewingSessionId !== activeSessionId) return; // don't inject into a read-only past session
    try {
      const response = await fetch("/api/minecraft/awareness");
      if (!response.ok) return;
      const data = await response.json();
      if (!data.has_message) return;

      appendMessage("Arika", data.response);
      reactToReply(data.response);
      refreshSessionsSidebar();

      if (data.audio_urls && data.audio_urls.length > 0) {
        Tts.enqueue(data.audio_urls);
      }
    } catch (error) {
      // Silent — this is a background convenience poll, not a user action.
    }
  }

  refreshMinecraftModeFlag();
  setInterval(refreshMinecraftModeFlag, 20000);
  setInterval(pollMinecraftAwareness, 5000);

  userInput.addEventListener("keypress", (e) => {
    if (e.key === "Enter") {
      Tts.unlockAudio();
      handleSend();
    }
  });
  sendBtn.addEventListener("click", () => {
    Tts.unlockAudio();
    handleSend();
  });

  // --- Sidebar slider ---
  const sidebar = document.getElementById("sidebar");
  const sliderBtn = document.getElementById("slider-btn");

  function updateSliderButton() {
    if (window.innerWidth <= 768) {
      sliderBtn.innerText = sidebar.classList.contains("collapsed") ? "☰" : "×";
    } else {
      sliderBtn.innerText = sidebar.classList.contains("collapsed") ? ">" : "<";
    }
  }

  sliderBtn.addEventListener("click", () => {
    sidebar.classList.toggle("collapsed");
    updateSliderButton();
    
    // --- NEW FIX: Force Avatar canvas to update after sidebar transition ---
    if (typeof Avatar !== 'undefined' && typeof Avatar.onResize === 'function') {
      setTimeout(() => {
        Avatar.onResize();
      }, 310);
    }
  });

  window.addEventListener("resize", updateSliderButton);
  updateSliderButton();

  if (window.innerWidth <= 768) {
    sidebar.classList.add("collapsed");
  }

  // --- Mobile: hide/show the chat overlay so Arika can be viewed full-screen ---
  const chatHideBtn = document.getElementById("chat-hide-btn");
  const chatWrapperEl = document.querySelector(".chat-container-wrapper");
  if (chatHideBtn && chatWrapperEl) {
    chatHideBtn.addEventListener("click", () => {
      const hidden = chatWrapperEl.classList.toggle("chat-hidden");
      chatHideBtn.innerText = hidden ? "👁️ Show" : "👁️ Chat";
      if (typeof Avatar !== "undefined" && typeof Avatar.onResize === "function") {
        setTimeout(() => Avatar.onResize(), 50);
      }
    });
  }

  // --- Sidebar: recent chats (sessions) ---
  async function refreshSessionsSidebar() {
    if (!historyList) return;
    try {
      const res = await fetch("/api/sessions");
      const data = await res.json();
      activeSessionId = data.active_session_id;

      historyList.innerHTML = "";
      if (!data.sessions || data.sessions.length === 0) {
        historyList.innerHTML = `<div class="history-empty">No chats yet</div>`;
        return;
      }
      data.sessions.forEach((s) => {
        const item = document.createElement("div");
        item.className = "history-item" + (s.session_id === viewingSessionId ? " active" : "");
        item.title = s.title;
        const label = s.title && s.title.length > 32 ? s.title.slice(0, 32) + "…" : (s.title || "New chat");
        const isCurrent = s.session_id === activeSessionId;
        item.innerHTML = `${label}<span class="history-item-meta">${isCurrent ? "current" : new Date(s.updated_at).toLocaleString()}</span>`;
        item.addEventListener("click", () => openSession(s.session_id));

        // delete button for each session
        const delBtn = document.createElement('button');
        delBtn.style.marginLeft = '8px';
        delBtn.style.float = 'right';
        delBtn.style.background = 'transparent';
        delBtn.style.border = 'none';
        delBtn.style.color = '#ff6b6b';
        delBtn.style.cursor = 'pointer';
        delBtn.title = 'Delete chat';
        delBtn.innerText = '🗑';
        delBtn.addEventListener('click', async (e) => {
          e.stopPropagation();
          if (!confirm('Delete this chat permanently?')) return;
          try {
            const res = await fetch(`/api/sessions/delete/${s.session_id}`, { method: 'POST' });
            if (res.ok) {
              refreshSessionsSidebar();
              if (viewingSessionId === s.session_id) {
                chatWindow.innerHTML = '';
                viewingSessionId = null;
              }
            } else {
              const data = await res.json();
              alert(data.message || 'Failed to delete chat');
            }
          } catch (err) {
            console.error('delete failed', err);
          }
        });
        item.appendChild(delBtn);
        historyList.appendChild(item);
      });
    } catch (e) {
      console.warn("[sessions] failed to load", e);
    }
  }

  async function openSession(sessionId) {
    try {
      const res = await fetch(`/api/sessions/${sessionId}`);
      if (!res.ok) return;
      const data = await res.json();

      viewingSessionId = sessionId;
      chatWindow.innerHTML = "";
      (data.messages || []).forEach((m) => {
        appendMessage("You", m.user);
        appendMessage("Arika", m.arika);
      });

      const isCurrent = sessionId === activeSessionId;
      setReadOnlyMode(!isCurrent);
      chatTitle.innerText = isCurrent ? "chat title" : "viewing past chat";
      refreshSessionsSidebar();
    } catch (e) {
      console.warn("[sessions] failed to open", e);
    }
  }

  backToCurrentBtn.addEventListener("click", () => {
    if (activeSessionId) openSession(activeSessionId);
  });

  resumeSessionBtn.addEventListener('click', async () => {
    if (!viewingSessionId) return;
    try {
      const res = await fetch(`/api/sessions/resume/${viewingSessionId}`, { method: 'POST' });
      if (res.ok) {
        // open the resumed session as active
        openSession(viewingSessionId);
      } else {
        console.warn('failed to resume session');
      }
    } catch (e) {
      console.warn('resume failed', e);
    }
  });

  document.getElementById("new-chat-btn").addEventListener("click", async () => {
    try {
      await fetch("/api/sessions/new", { method: "POST" });
      chatWindow.innerHTML = "";
      viewingSessionId = null;
      setReadOnlyMode(false);
      chatTitle.innerText = "chat title";
      refreshSessionsSidebar();
    } catch (e) {
      console.warn("[sessions] failed to start new chat", e);
    }
  });

  async function doLogout() {
    await fetch("/api/auth/logout", { method: "POST" });
    window.location.href = "/login";
  }
  document.getElementById("logout-btn").addEventListener("click", doLogout);
  const mobileLogoutBtn = document.getElementById("mobile-logout-btn");
  if (mobileLogoutBtn) mobileLogoutBtn.addEventListener("click", doLogout);

  refreshSessionsSidebar();

  const micStatus = document.getElementById("mic-status");

  // --- Live audio (voice) mode ---
  Stt.init({
    wakeWord: window.ARIKA_SETTINGS?.wake_word ?? "arika",
    lang: window.ARIKA_SETTINGS?.stt_lang || "en-IN",
    onWake: (transcript) => handleSend(transcript),
    onIgnored: (transcript) => {
      userInput.value = "Ignored: " + transcript;
      setTimeout(() => {
        if (liveBtn.classList.contains("active") && !Tts.isSpeaking()) userInput.value = "";
      }, 1500);
    },
    onStateChange: ({ listening }) => {
      const ww = window.ARIKA_SETTINGS?.wake_word;
      userInput.placeholder = listening
        ? (ww ? `Listening for wake word "${ww}"...` : "Listening... (no wake word — just talk)")
        : "type here.......";
    },
    onDebug: (type, message) => {
      if (!micStatus) return;
      micStatus.innerText = message;
      console.log(`[stt:${type}]`, message);
    },
  });

  // NOTE: previously this hid the button entirely whenever the browser
  // didn't expose window.SpeechRecognition/webkitSpeechRecognition, which
  // is exactly why it silently "never showed up" on some phones — there
  // was no feedback at all. Now we keep it visible but disabled, with a
  // reason, so it's obvious what's going on instead of looking broken.
  const liveBtnLabel = liveBtn.querySelector(".live-audio-label");

  if (!Stt.isSupported()) {
    liveBtn.classList.add("unsupported");
    const reason = window.isSecureContext
      ? "This browser doesn't support voice recognition (Web Speech API). Try Chrome."
      : "Voice mode needs a secure (https) connection with a trusted certificate — " +
        "on a self-signed dev cert, Chrome on Android often won't expose the mic API " +
        "even after you click through the warning. Try trusting the certificate, or use Chrome on desktop.";
    liveBtn.title = reason;
    if (liveBtnLabel) {
      liveBtnLabel.innerText = "live audio mode (unavailable)";
    } else {
      liveBtn.innerText = "live audio mode (unavailable)";
    }
    if (micStatus) micStatus.innerText = reason;
    liveBtn.addEventListener("click", () => {
      if (micStatus) micStatus.innerText = reason;
    });
  } else {
    liveBtn.addEventListener("click", () => {
      Tts.unlockAudio();
      const isOn = Stt.toggle();
      liveBtn.classList.toggle("active", isOn);
      if (liveBtnLabel) {
        liveBtnLabel.innerText = isOn ? "active listening" : "live audio mode";
      } else {
        liveBtn.innerText = isOn ? "🔴 active listening" : "live audio mode";
      }
      if (!isOn) {
        userInput.value = "";
        if (micStatus) micStatus.innerText = "";
      }
    });
  }
// --- ATTACH MENU & TIC TAC TOE LOGIC ---
    const attachMenu = document.getElementById("attach-menu");
    const menuSendPhoto = document.getElementById("menu-send-photo");
    const menuTicTacToe = document.getElementById("menu-tic-tac-toe");
    const tttWindow = document.getElementById("tictactoe-window");
    const tttClose = document.getElementById("tictactoe-close");
    
    // Override old attachBtn listener by cloning and replacing it
    const attachBtnClone = attachBtn.cloneNode(true);
    attachBtn.parentNode.replaceChild(attachBtnClone, attachBtn);
    
    attachBtnClone.addEventListener("click", (e) => {
        e.stopPropagation();
        attachMenu.classList.toggle("show");
    });
    
    document.addEventListener("click", (e) => {
        if (!attachMenu.contains(e.target) && e.target !== attachBtnClone) {
            attachMenu.classList.remove("show");
        }
    });
    
    menuSendPhoto.addEventListener("click", () => {
        attachMenu.classList.remove("show");
        document.getElementById("image-input").click();
    });
    
    menuTicTacToe.addEventListener("click", () => {
        attachMenu.classList.remove("show");
        tttWindow.classList.add("show");
        resetTicTacToe();
        notifyArikaStatus("We just started a Tic Tac Toe game. I am X and you are O. Tease me that you will win!");
    });
    
    tttClose.addEventListener("click", () => {
        tttWindow.classList.remove("show");
        resetTicTacToe();
    });
    
    // --- MOVABLE WINDOW ---
    const tttHeader = document.getElementById("tictactoe-header");
    let isDragging = false, startX, startY, initialX, initialY;
    
    function startDrag(e) {
        isDragging = true;
        const clientX = e.type.includes('mouse') ? e.clientX : e.touches[0].clientX;
        const clientY = e.type.includes('mouse') ? e.clientY : e.touches[0].clientY;
        startX = clientX;
        startY = clientY;
        initialX = tttWindow.offsetLeft;
        initialY = tttWindow.offsetTop;
        tttWindow.style.transform = "none";
    }
    
    function doDrag(e) {
        if (!isDragging) return;
        e.preventDefault();
        const clientX = e.type.includes('mouse') ? e.clientX : e.touches[0].clientX;
        const clientY = e.type.includes('mouse') ? e.clientY : e.touches[0].clientY;
        tttWindow.style.left = (initialX + clientX - startX) + "px";
        tttWindow.style.top = (initialY + clientY - startY) + "px";
    }
    
    function stopDrag() { isDragging = false; }
    
    tttHeader.addEventListener("mousedown", startDrag);
    document.addEventListener("mousemove", doDrag);
    document.addEventListener("mouseup", stopDrag);
    tttHeader.addEventListener("touchstart", startDrag, {passive: false});
    document.addEventListener("touchmove", doDrag, {passive: false});
    document.addEventListener("touchend", stopDrag);
    
    // --- GAME AI AND CHAT INTEGRATION ---
    let tttBoard = ["", "", "", "", "", "", "", "", ""];
    let gameActive = false;
    const cells = document.querySelectorAll(".ttc-cell");
    
    // Send background message to Arika to trigger commentary
    async function notifyArikaStatus(promptText) {
        const typingDiv = window.ArikaChat.appendMessage("Arika", "Thinking about the game...");
        try {
            const response = await fetch("/api/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ user_message: `[System Event: Tic Tac Toe] ${promptText}. Respond with a short 1-line teasing remark. dont use emojis` })
            });
            const data = await response.json();
            typingDiv.remove();
            window.ArikaChat.appendMessage("Arika", data.response);
            if (data.audio_urls && data.audio_urls.length > 0) Tts.enqueue(data.audio_urls);
            if (window.Avatar && typeof Avatar.setEmotion === 'function') Avatar.setEmotion('happy');
            window.ArikaChat.refreshSessionsSidebar();
        } catch(e) {
            typingDiv.remove();
        }
    }
    
    function checkWin(player) {
        const winPatterns = [ [0,1,2], [3,4,5], [6,7,8], [0,3,6], [1,4,7], [2,5,8], [0,4,8], [2,4,6] ];
        return winPatterns.some(pattern => {
            return pattern.every(index => tttBoard[index] === player);
        });
    }
    
    function arikaMove() {
        if (!gameActive) return;
        let emptyCells = tttBoard.map((val, idx) => val === "" ? idx : null).filter(val => val !== null);
        if (emptyCells.length === 0) return;
        
        let move = emptyCells[Math.floor(Math.random() * emptyCells.length)];
        tttBoard[move] = "O";
        cells[move].innerText = "O";
        cells[move].style.color = "#f38ba8";
        
        if (checkWin("O")) {
            gameActive = false;
            notifyArikaStatus("I lost the Tic Tac Toe game to you. Roast me and celebrate your win!");
            return;
        }
        if (!tttBoard.includes("")) {
            gameActive = false;
            notifyArikaStatus("The game ended in a draw. Say something funny about how we are evenly matched.");
            return;
        }
        
        // Randomly talk trash during the game
        if (Math.random() > 0.6) {
            notifyArikaStatus("We are mid-game. I played X, you played O. Tease me about my strategy.");
        }
    }
    
    function resetTicTacToe() {
        tttBoard = ["", "", "", "", "", "", "", "", ""];
        gameActive = true;
        cells.forEach(c => { c.innerText = ""; });
    }
    
    cells.forEach(cell => {
        cell.addEventListener("click", () => {
            const index = cell.getAttribute("data-index");
            if (tttBoard[index] === "" && gameActive) {
                // User move
                tttBoard[index] = "X";
                cell.innerText = "X";
                cell.style.color = "#a78bfa";
                
                if (checkWin("X")) {
                    gameActive = false;
                    notifyArikaStatus("I actually won the Tic Tac Toe game against you! React to your loss with surprise.");
                    return;
                }
                if (!tttBoard.includes("")) {
                    gameActive = false;
                    notifyArikaStatus("The game ended in a draw. Say something funny about how we are evenly matched.");
                    return;
                }
                
                // Let Arika play O
                setTimeout(arikaMove, 600);
            }
        });
    });
  window.ArikaChat = { appendMessage, refreshSessionsSidebar };
});