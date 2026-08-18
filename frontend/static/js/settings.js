/* settings.js — the "uncoming features" from the sidebar, now live:
 * change API key / TTS voice / wake word from the web UI. Profile facts are
 * now saved automatically by Arika's save_profile tool during chat, so
 * there's no manual profile form here anymore. */

const ArikaSettings = (() => {
  let modal, apiKeyInput, apiKeyStatus, voiceSelect, modelSelect, modelNote, wakeWordInput, showAvatarToggle, phoneAdbAddressInput, emailAddressInput, emailAppPasswordInput, browserDebugPortInput, minecraftHostInput, minecraftPortInput, minecraftUsernameInput, minecraftAuthSelect, saveBtn, closeBtn;
  let modelsById = {};

  function open() {
    modal.classList.add("open");
  }

  function close() {
    modal.classList.remove("open");
  }

  function _updateModelNote() {
    const model = modelsById[modelSelect.value];
    if (model && modelNote) {
      modelNote.innerText = model.note || "";
    }
  }

  async function loadIntoForm() {
    try {
      const res = await fetch("/api/settings");
      const data = await res.json();

      voiceSelect.innerHTML = "";
      (data.available_tts_voices || []).forEach((v) => {
        const opt = document.createElement("option");
        opt.value = v.id;
        opt.innerText = v.label;
        voiceSelect.appendChild(opt);
      });
      voiceSelect.value = data.settings.tts_voice;

      modelSelect.innerHTML = "";
      modelsById = {};
      (data.available_gemini_models || []).forEach((m) => {
        modelsById[m.id] = m;
        const opt = document.createElement("option");
        opt.value = m.id;
        const tag = m.tier === "free" ? "🟢 Free" : "💰 Paid";
        opt.innerText = `${m.label} — ${tag}`;
        modelSelect.appendChild(opt);
      });
      modelSelect.value = data.settings.gemini_model;
      _updateModelNote();

      wakeWordInput.value = data.settings.wake_word;
      showAvatarToggle.checked = data.settings.show_avatar !== false;
      phoneAdbAddressInput.value = data.settings.phone_adb_address || "";
      emailAddressInput.value = data.settings.email_address || "";
      // email_app_password is never sent back from the server — leave blank
      browserDebugPortInput.value = data.settings.browser_debug_port || "";
      
      // Minecraft settings
      minecraftHostInput.value = data.settings.minecraft_host || "localhost";
      minecraftPortInput.value = data.settings.minecraft_port || 25565;
      minecraftUsernameInput.value = data.settings.minecraft_username || "Arika";
      minecraftAuthSelect.value = data.settings.minecraft_auth || "offline";

      if (window.Avatar && typeof Avatar.setVisible === 'function') {
        Avatar.setVisible(showAvatarToggle.checked);
      }

      apiKeyStatus.innerText = data.has_api_key
        ? "✅ API key is set (leave blank to keep it)"
        : "⚠️ No API key set yet — chat won't work until you add one.";

      emailAppPasswordInput.placeholder = data.has_email_password
        ? "•••••••• (saved — leave blank to keep it)"
        : "leave blank to keep current";

      window.ARIKA_SETTINGS = data.settings;
    } catch (e) {
      console.warn("[settings] failed to load", e);
    }
  }

  async function save() {
    const payload = {
      settings: {
        tts_voice: voiceSelect.value,
        gemini_model: modelSelect.value,
        wake_word: wakeWordInput.value.trim(), // empty = no wake word needed
        show_avatar: showAvatarToggle.checked,
        phone_adb_address: phoneAdbAddressInput.value.trim(), // e.g. 192.168.1.42:5555, empty = USB only
        email_address: emailAddressInput.value.trim(),
        email_app_password: emailAppPasswordInput.value.trim(), // empty = keep existing saved password
        browser_debug_port: browserDebugPortInput.value.trim(), // e.g. 9222, empty = default launch mode
        // Minecraft settings
        minecraft_host: minecraftHostInput.value.trim() || "localhost",
        minecraft_port: parseInt(minecraftPortInput.value) || 25565,
        minecraft_username: minecraftUsernameInput.value.trim() || "Arika",
        minecraft_auth: minecraftAuthSelect.value || "offline",
      },
    };

    await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const apiKey = apiKeyInput.value.trim();
    if (apiKey) {
      await fetch("/api/settings/api-key", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: apiKey }),
      });
      apiKeyInput.value = "";
    }

    emailAppPasswordInput.value = "";

    if (window.Stt) Stt.configure({ wakeWord: payload.settings.wake_word });

    await loadIntoForm();
    close();
  }

  function init() {
    modal = document.getElementById("settings-modal");
    apiKeyInput = document.getElementById("settings-api-key");
    apiKeyStatus = document.getElementById("settings-api-key-status");
    voiceSelect = document.getElementById("settings-voice");
    modelSelect = document.getElementById("settings-model");
    modelNote = document.getElementById("settings-model-note");
    wakeWordInput = document.getElementById("settings-wake-word");
    showAvatarToggle = document.getElementById("settings-show-avatar");
    phoneAdbAddressInput = document.getElementById("settings-phone-adb-address");
    emailAddressInput = document.getElementById("settings-email-address");
    emailAppPasswordInput = document.getElementById("settings-email-app-password");
    browserDebugPortInput = document.getElementById("settings-browser-debug-port");
    minecraftHostInput = document.getElementById("settings-minecraft-host");
    minecraftPortInput = document.getElementById("settings-minecraft-port");
    minecraftUsernameInput = document.getElementById("settings-minecraft-username");
    minecraftAuthSelect = document.getElementById("settings-minecraft-auth");
    saveBtn = document.getElementById("settings-save");
    closeBtn = document.getElementById("settings-close");

    modelSelect.addEventListener("change", _updateModelNote);

    document.getElementById("settings-open-btn").addEventListener("click", () => {
      loadIntoForm();
      open();
    });
    closeBtn.addEventListener("click", close);
    saveBtn.addEventListener("click", save);

    if (window.ARIKA_HAS_API_KEY === false) {
      loadIntoForm();
      open();
    }

    if (window.Avatar && typeof Avatar.setVisible === 'function') {
      Avatar.setVisible(showAvatarToggle && showAvatarToggle.checked !== false);
    }
  }

  return { init, open, close };
})();

document.addEventListener("DOMContentLoaded", () => {
  ArikaSettings.init();
  window.ArikaSettings = ArikaSettings;
});
