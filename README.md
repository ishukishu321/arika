# Arika AI Chat

Arika is a Flask-based AI assistant web application with per-user memory, session management, voice features, and Google Gemini integration.

## Overview

This project is a personal AI assistant designed to remember conversations, save and retrieve long-term memory, manage multiple sessions, and support both logged-in users and guest access.

It uses:
- Python + Flask for the backend
- Google Gemini for AI responses
- A browser-based dark-themed chat UI
- STT and TTS support for voice interaction
- File-based persistence for users, settings, memory, and chat sessions

## Key Features

- **User accounts and guest mode**
  - Register new users and log in
  - Continue as guest without an account
  - Separate memory and sessions for each user and guest

- **Long-term memory and summarization**
  - Rolling short-term memory for the current chat
  - Automatic summarization of older conversation chunks into summaries
  - Mega-summary generation after 5 summaries
  - Tag-based long-term memory search for relevant recall
  - Memory review is scoped to the current user

- **Session management**
  - Auto-generated chat session IDs in the format `DD-MM-YYYY-XXX`
  - Persistent session transcript storage per user
  - View past chats
  - Resume an old chat into the active working memory
  - Delete old chats from the web UI

- **Profile and settings**
  - Save user profile data via the web settings panel
  - Delete user profile information from the web UI
  - Configure TTS voice and Gemini model
  - Set the wake word for live speech recognition
  - Save Gemini API key from the web interface

- **Voice interaction**
  - Browser-based STT live listening with wake-word support
  - TTS audio generation using the `edge-tts` library
  - Microphone mode prefers silence while the user speaks and resumes after TTS

- **Dark, responsive web UI**
  - Black and grey design
  - Responsive layout for desktop and mobile
  - Chat history sidebar with current and past sessions
  - Input and feedback optimized for modern devices

- **Backend command flow**
  - Uses `<COMMAND>...</COMMAND>` blocks in LLM responses to perform actions
  - Supports `review_mem` to fetch long-term memory
  - Supports `save_profile` to store user profile details

## Project Structure

- `main.py` - entry point for running the app
- `backend/` - Flask backend and memory management
  - `app.py` - main Flask application and API routes
  - `gemini.py` - Gemini API wrapper and system instruction handling
  - `prompt_builder.py` - build chat prompts with history and memory context
  - `parser.py` - parse AI responses and extract command blocks
  - `command_router.py` - execute backend actions from AI commands
  - `auth_manager.py` - account registration and login validation
  - `settings_manager.py` - settings persistence and available voice/model options
  - `user_context.py` - user-scoped path resolution for per-user memory files
  - `memory_manager/` - memory storage and search
    - `short_term.py` - rolling short-term memory for the active chat
    - `summary_maker.py` - summary / mega-summary creation
    - `long_term_mem.py` - long-term memory save/load logic
    - `long_term_mem_manager.py` - long-term memory search by tag
    - `profile.py` - user profile persistence
    - `session_manager.py` - session transcripts and recent chat management
- `frontend/` - front-end pages and static assets
  - `index.html` - main chat UI
  - `login.html` - login/register/guest page
  - `web.py` - app frontend mounting wrapper
  - `static/js/` - chat and settings logic
  - `static/css/` - UI stylesheet if present

## Installation

1. Install Python dependencies:

```bash
pip install -r requirements.txt
```

2. Run the application from the project root:

```bash
python main.py
```

3. Open your browser at:

```text
https://localhost:5000
```

> The app uses `ssl_context='adhoc'` so the browser can request microphone permissions securely.

## Usage

- Open the login page and sign in or continue as a guest.
- Add your Gemini API key in Settings before sending messages.
- Start chatting with Arika in the main interface.
- Use the settings modal to set TTS voice, wake word, preferred Gemini model, and profile data.
- Resume a previous chat from the sidebar or create a new chat.
- Delete old sessions from the sidebar if no longer needed.
- Speak using live voice mode if your browser supports the Web Speech API.

## Memory Behavior

- The assistant keeps the last few exchanges in short-term memory to preserve context.
- Older chat exchanges are summarized automatically once the short-term buffer reaches the configured threshold.
- After several summaries are created, Arika generates a consolidated mega summary with tags.
- Long-term memory search is **semantic (embedding-based)**, not just tag matching:
  - Every user message is auto-searched against the long-term archive using
    vector similarity (`fastembed`, multilingual model — matches Hindi/Hinglish
    queries against memory content, not just literal keyword overlap).
  - When the AI explicitly decides to review memory, it issues a `review_mem`
    command; the backend runs the same semantic search first, falling back to
    the older tag/keyword matcher only if the embedding backend is unavailable
    or finds nothing.
  - If matching memories are found, Arika will answer using the retrieved
    long-term context.
- After changing the embedding model (`backend/memory_manager/embeddings.py`),
  run `python -m scripts.migrate_embeddings --force` once — existing entries'
  stored vectors are tied to the model that generated them and won't match
  well against a different model's query vectors otherwise.

## Notes

- Image upload is supported: attach an image (PNG/JPEG/WEBP/GIF, max 10MB)
  alongside a message and Gemini will see it via vision. Uploaded images are
  saved under `frontend/static/uploads/chat/`.
- The admin persona is configured so Arika knows the admin identity is `ishu`.
- Profile data and memory are stored separately for each logged-in user and for guest mode.
- The Gemini API key is stored in `backend/memory/api_key.txt` and shared across all users.
- Automation (both PC and phone) is Admin-only — see `backend/admin_manager.py`.
- Phone automation uses ADB; the phone's saved wireless-debugging address
  (Settings > Phone adb address) is auto-reconnected on every startup.
- `automation_scripts/` (project root) is a sandboxed folder for `run_script`
  — only files placed there can be run from chat, never an arbitrary path.
- `send_email` needs a Gmail address + App Password saved in Settings
  (not the normal account password).
- `webcam_photo`, `mic_mute` (Windows), and `set_reminder`'s optional toast
  popup need extra packages — see the "optional" section of requirements.txt.
- `phone_screen_mirror` needs the separate `scrcpy` tool installed and on PATH.

## Dependencies

- `flask`
- `edge-tts`
- `google-genai`
- `fastembed` — semantic (RAG) long-term memory search, ONNX-based

## License

This project does not include a license file. Add one if you want to make the project open source or clarify reuse terms.
