/* tts.js — plays the mp3 chunk URLs the backend generates for each reply. */

const Tts = (() => {
  let queue = [];
  let speaking = false;
  let currentAudio = null;
  let currentFile = null;
  let onQueueEmpty = () => {};

  // --- lip-sync: volume-driven mouth movement, fed to window.Avatar ---
  let audioCtx = null;
  let analyser = null;
  let freqData = null;
  let lipSyncRafId = null;

  function unlockAudio() {
    // Must be called directly inside a real user-click handler (not after an
    // await/fetch), or the browser's autoplay policy keeps the context
    // suspended forever and every subsequent audio.play() stays silent even
    // though playback "succeeds".
    try {
      if (!audioCtx) {
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      }
      if (audioCtx.state === "suspended") {
        audioCtx.resume();
      }
    } catch (err) {
      console.warn("[tts] audio unlock failed:", err);
    }
  }

  function ensureAudioGraph(audioEl) {
    try {
      if (!audioCtx) {
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      }
      if (audioCtx.state === "suspended") {
        audioCtx.resume();
      }
      const source = audioCtx.createMediaElementSource(audioEl);
      analyser = audioCtx.createAnalyser();
      analyser.fftSize = 256;
      freqData = new Uint8Array(analyser.frequencyBinCount);
      source.connect(analyser);
      analyser.connect(audioCtx.destination);
    } catch (err) {
      console.warn("[tts] lip-sync audio graph failed:", err);
      analyser = null;
    }
  }

  function startLipSync() {
    if (!analyser || !window.Avatar) return;
    const loop = () => {
      if (!analyser) return;
      analyser.getByteTimeDomainData(freqData);
      let sumSq = 0;
      for (let i = 0; i < freqData.length; i++) {
        const v = (freqData[i] - 128) / 128;
        sumSq += v * v;
      }
      const rms = Math.sqrt(sumSq / freqData.length);
      window.Avatar.setMouth(Math.min(1, rms * 4)); // amplify quiet edge-tts audio
      lipSyncRafId = requestAnimationFrame(loop);
    };
    loop();
  }

  function stopLipSync() {
    if (lipSyncRafId) cancelAnimationFrame(lipSyncRafId);
    lipSyncRafId = null;
    if (window.Avatar) window.Avatar.setMouth(0);
  }

  function setOnQueueEmpty(cb) {
    onQueueEmpty = cb;
  }

  function isSpeaking() {
    return speaking;
  }

  function filenameFromUrl(url) {
    try {
      const parsed = new URL(url, window.location.origin);
      return parsed.pathname.split("/").pop();
    } catch (err) {
      return null;
    }
  }

  async function deleteAudioFiles(filenames) {
    if (!filenames || filenames.length === 0) return;
    try {
      await fetch("/api/audio/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filenames }),
      });
    } catch (err) {
      console.warn("[tts] cleanup failed:", err);
    }
  }

  function cleanupFile(filename) {
    if (!filename) return;
    deleteAudioFiles([filename]);
  }

  function enqueue(urls) {
    if (!urls || urls.length === 0) return;
    queue = queue.concat(urls);
    if (!speaking) {
      _playNext();
    }
  }

  function _playNext() {
    if (queue.length === 0) {
      speaking = false;
      onQueueEmpty();
      return;
    }

    // If the microphone is currently listening (user speaking), postpone
    // playback to avoid talking over the user.
    if (window.Stt && typeof window.Stt.isListening === 'function' && window.Stt.isListening()) {
      // try again shortly
      setTimeout(_playNext, 500);
      return;
    }

    speaking = true;
    const url = queue.shift();
    currentFile = filenameFromUrl(url);
    currentAudio = new Audio(url);
    ensureAudioGraph(currentAudio);
    currentAudio.play().then(() => {
      startLipSync();
    }).catch((err) => {
      console.warn("[tts] playback blocked/failed:", err);
      cleanupFile(currentFile);
      currentFile = null;
      _playNext();
    });
    currentAudio.onended = () => {
      stopLipSync();
      cleanupFile(currentFile);
      currentFile = null;
      _playNext();
    };
    currentAudio.onerror = () => {
      stopLipSync();
      cleanupFile(currentFile);
      currentFile = null;
      _playNext();
    };
  }

  function stopAll() {
    const pendingFiles = queue.map(filenameFromUrl).filter(Boolean);
    const current = currentFile ? [currentFile] : [];
    queue = [];
    if (currentAudio) {
      currentAudio.pause();
      currentAudio = null;
    }
    stopLipSync();
    currentFile = null;
    speaking = false;
    deleteAudioFiles([...current, ...pendingFiles]);
  }

  return { enqueue, isSpeaking, stopAll, setOnQueueEmpty, unlockAudio };
})();
