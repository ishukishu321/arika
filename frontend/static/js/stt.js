/* stt.js — wake-word live listening via the browser's Web Speech API.
 *
 * Bug fix history:
 * - Previously `recognition.lang` was hardcoded to 'hi-IN'. For Hinglish
 *   speakers Chrome mostly returns Devanagari script in that mode, so the
 *   Latin-alphabet wake-word check (`startsWith('a')`) almost never
 *   matched — that's why "live audio mode" looked broken. Default is now
 *   'en-IN' (good for Hinglish spoken in Latin script) and is configurable
 *   from Settings.
 * - `recognition.start()` was being called from three places (toggle,
 *   onend, and after TTS finishes) with no guard, so it would sometimes
 *   throw InvalidStateError ("already started") and silently die. There's
 *   now a single `active` flag guarding every start/stop.
 */

const Stt = (() => {
  let recognition = null;
  let supported = false;
  let active = false; // user has toggled live mode ON
  let listening = false; // recognition.start() has actually fired
  let paused = false; // deliberately paused for processing/TTS — don't auto-restart
  let wakeWord = "arika";
  let lang = "en-IN";

  let onWake = () => {};
  let onIgnored = () => {};
  let onStateChange = () => {};
  let onDebug = () => {};
  let restartTimer = null;

  function isSupported() {
    return supported;
  }

  function configure({ wakeWord: w, lang: l } = {}) {
    if (typeof w === "string") wakeWord = w.trim().toLowerCase();
    if (l) lang = l;
    if (recognition) recognition.lang = lang;
  }

  function _matchesWakeWord(rawTranscript) {
    const text = rawTranscript.trim().toLowerCase();
    if (!text) return false;

    // Empty wake word = wake-word mode disabled entirely. Every sentence
    // the mic hears goes straight to chat, no "Arika, ..." needed.
    if (!wakeWord) return true;

    return (
      text.startsWith(wakeWord) ||
      text.includes(` ${wakeWord}`) ||
      text.startsWith(wakeWord.charAt(0)) // short/loose fallback, e.g. just "a"
    );
  }

  function _scheduleRestart(delay) {
    if (restartTimer) return; // already have one queued, don't stack another
    restartTimer = setTimeout(() => {
      restartTimer = null;
      _safeStart();
    }, delay);
  }

  function _safeStart() {
    if (!supported || !active || listening) return;
    try {
      recognition.start();
    } catch (e) {
      // Already started / not ready yet — ignore, onstart/onend will settle it.
    }
  }

  function _safeStop() {
    if (!supported) return;
    try {
      recognition.stop();
    } catch (e) {
      /* ignore */
    }
  }

  function init({ wakeWord: w, lang: l, onWake: wakeCb, onIgnored: ignoredCb, onStateChange: stateCb, onDebug: debugCb } = {}) {
    if (typeof w === "string") wakeWord = w.trim().toLowerCase();
    if (l) lang = l;
    if (wakeCb) onWake = wakeCb;
    if (ignoredCb) onIgnored = ignoredCb;
    if (stateCb) onStateChange = stateCb;
    if (debugCb) onDebug = debugCb;

    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRec) {
      supported = false;
      console.warn("[stt] Web Speech API not supported in this browser.");
      return;
    }

    supported = true;
    recognition = new SpeechRec();
    recognition.lang = lang;
    recognition.continuous = true;
    recognition.interimResults = false;

    recognition.onstart = () => {
      listening = true;
      onStateChange({ listening: true });
      onDebug("mic_started", "Mic is live, listening...");
    };

    recognition.onspeechstart = () => {
      onDebug("speech_detected", "Heard something, processing...");
    };

    recognition.onresult = (event) => {
      const current = event.resultIndex;
      const transcript = event.results[current][0].transcript.trim();
      onDebug("transcript", `Heard: "${transcript}"`);

      if (_matchesWakeWord(transcript)) {
        paused = true; // stop = intentional; don't let onend restart it early
        _safeStop(); // pause mic while we process this turn
        onWake(transcript);
      } else {
        onDebug("ignored", `Ignored (wake word "${wakeWord}" not matched): "${transcript}"`);
        onIgnored(transcript);
      }
    };

    recognition.onerror = (event) => {
      listening = false;
      onDebug("error", `Mic error: ${event.error}`);
      // onend always fires right after onerror in every browser that
      // implements this API, so only onend needs to schedule a restart —
      // scheduling here too just caused a duplicate start() race.
    };

    recognition.onend = () => {
      listening = false;
      onStateChange({ listening: false });
      if (active && !paused) {
        _scheduleRestart(400);
      }
    };
  }

  function enable() {
    if (!supported) return false;
    active = true;
    _safeStart();
    return true;
  }

  function disable() {
    active = false;
    paused = false;
    if (restartTimer) {
      clearTimeout(restartTimer);
      restartTimer = null;
    }
    _safeStop();
  }

  function toggle() {
    if (active) {
      disable();
      return false;
    }
    return enable();
  }

  /** Call this once Arika has finished speaking, so live mode resumes listening. */
  function resumeIfActive() {
    paused = false;
    if (active && !listening) {
      _safeStart();
    }
  }
  function isListening() { return listening; }

  return { init, configure, enable, disable, toggle, resumeIfActive, isSupported, isListening };
})();
