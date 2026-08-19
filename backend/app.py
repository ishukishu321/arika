import os
import secrets
import time
import uuid
from pathlib import Path

import re
from flask import Flask, render_template, request, jsonify, url_for, session, redirect
from werkzeug.utils import secure_filename

from google.genai import errors as genai_errors
from backend.gemini import ask_gemini, has_api_key, save_api_key, MissingAPIKeyError
from backend.prompt_builder import build_prompt
from backend.parser import process
from backend.command_router import execute, AUTOMATION_ACTIONS
from backend.memory_manager.short_term import save_chat, get_recent_messages, load_messages, clear_memory
from backend.memory_manager.long_term_mem_manager import get_memory_context_for_prompt
from backend.memory_manager import session_manager
from backend import settings_manager
from backend import auth_manager
from backend import admin_manager
from backend import user_context
from backend import agent_planner
from backend import minecraft_manager
from backend import minecraft_awareness
from backend.speech import tts as tts_module
from backend.speech import stt as stt_module

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
SECRET_KEY_FILE = Path(user_context.MEMORY_ROOT) / "flask_secret.key"


def _normalize_reply(reply):
    """ask_gemini() now returns {"text": ..., "commands": [...]} built from
    Gemini's native function_calls (reliable, structured). We still run the
    old regex-based `process()` over the text as a safety net in case the
    model ever free-types a legacy <COMMAND> block, and merge both lists —
    but the native function_calls are the primary path now."""
    legacy = process(reply["text"])
    return {
        "response": legacy["response"],
        "commands": reply["commands"] + legacy["commands"],
    }


def _safe_ask_gemini(prompt, **kwargs):
    """Wraps ask_gemini() for the FOLLOW-UP calls inside /api/chat (memory
    review reply, task/automation follow-up reply, plan auto-continuation
    steps) — none of which were previously wrapped in any try/except.

    Before this, if Gemini failed on any of those (rate limit, timeout,
    safety block, bad model name, etc.) the whole request raised an
    unhandled 500 — losing the reply that had ALREADY been generated and
    saved earlier in the same request, with no graceful message to the
    user at all.

    Returns the normal ask_gemini() reply dict on success, or None on
    failure (after logging) so callers can degrade gracefully instead of
    crashing the request.

    The FIRST ask_gemini call in api_chat() is intentionally NOT routed
    through this helper — it needs to raise MissingAPIKeyError so that
    call site's existing try/except can still return its dedicated 401
    response.
    """
    try:
        return ask_gemini(prompt, enable_tools=True, **kwargs)
    except Exception as e:
        print(f"[API Chat] Follow-up ask_gemini call failed: {e}")
        return None


def _get_or_create_secret_key() -> str:
    """A persistent secret key so login sessions survive server restarts."""
    SECRET_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if SECRET_KEY_FILE.exists():
        key = SECRET_KEY_FILE.read_text(encoding="utf-8").strip()
        if key:
            return key
    key = secrets.token_hex(32)
    SECRET_KEY_FILE.write_text(key, encoding="utf-8")
    return key


def create_app():
    app = Flask(
        __name__,
        template_folder=str(FRONTEND_DIR),
        static_folder=str(FRONTEND_DIR / "static"),
    )
    app.secret_key = _get_or_create_secret_key()

    admin_manager.bootstrap_admin_if_needed()

    from backend import calendar_manager
    calendar_manager.start_background_checker()

    audio_dir = os.path.join(app.root_path, "..", "frontend", "static", "audio")
    audio_dir = os.path.abspath(audio_dir)
    os.makedirs(audio_dir, exist_ok=True)
    app.config["AUDIO_DIR"] = audio_dir

    def _minecraft_awareness_callback(status, events):
        # Runs on minecraft_manager's background poll thread (no active
        # Flask request) — test_request_context() is what makes url_for()
        # work here for building the audio URLs.
        with app.test_request_context():
            minecraft_awareness.check_and_maybe_comment(
                status,
                events,
                ask_gemini_fn=ask_gemini,
                tts_generate_fn=tts_module.generate_audio_chunks_sync,
                save_chat_fn=save_chat,
                audio_url_builder=lambda fname: url_for("static", filename=f"audio/{fname}"),
                audio_dir=app.config["AUDIO_DIR"],
            )

    minecraft_manager.register_awareness_callback(_minecraft_awareness_callback)

    upload_dir = os.path.join(app.root_path, "..", "frontend", "static", "uploads", "chat")
    upload_dir = os.path.abspath(upload_dir)
    os.makedirs(upload_dir, exist_ok=True)
    app.config["CHAT_UPLOAD_DIR"] = upload_dir

    # ---------------- Auth plumbing ----------------

    PUBLIC_ENDPOINTS = {
        "login_page", "static",
        "api_auth_login", "api_auth_register", "api_auth_guest",
    }

    @app.before_request
    def _load_user_context():
        """Runs before every request. If someone is logged in (real user or
        guest), point every memory_manager module at their files for the
        rest of this request. Otherwise, bounce non-public routes to /login."""
        user_id = session.get("user_id")
        is_guest = session.get("is_guest", False)

        if user_id:
            user_context.set_current_user(user_id, is_guest)
            return None

        if request.endpoint in PUBLIC_ENDPOINTS:
            return None

        if request.path.startswith("/api/"):
            return jsonify({"error": "not_logged_in", "message": "Please log in first."}), 401
        return redirect("/login")

    # ---------------- Pages ----------------

    @app.route("/login")
    def login_page():
        if session.get("user_id"):
            return redirect("/")
        return render_template("login.html")

    @app.route("/")
    def index():
        session_id = session.get("session_id")
        if not session_id:
            session_id = session_manager.create_session()
            session["session_id"] = session_id

        conversation = get_recent_messages(limit=10)
        return render_template(
            "index.html",
            conversation=conversation,
            has_api_key=has_api_key(),
            settings=settings_manager.load_settings(),
            login_id=session.get("user_id"),
            is_guest=session.get("is_guest", False),
        )

    # ---------------- Auth API ----------------

    @app.route("/api/auth/register", methods=["POST"])
    def api_auth_register():
        data = request.json or {}
        login_id = (data.get("login_id") or "").strip()
        password = data.get("password") or ""

        try:
            auth_manager.register_user(login_id, password)
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)}), 400

        user_context.set_current_user(login_id.lower(), is_guest=False)
        session.clear()
        session["user_id"] = login_id.lower()
        session["is_guest"] = False
        session["session_id"] = session_manager.create_session()
        clear_memory()  # fresh working memory for this brand-new account
        return jsonify({"status": "ok", "login_id": login_id.lower()})

    @app.route("/api/auth/login", methods=["POST"])
    def api_auth_login():
        data = request.json or {}
        login_id = (data.get("login_id") or "").strip()
        password = data.get("password") or ""

        if not auth_manager.verify_user(login_id, password):
            return jsonify({"status": "error", "message": "Wrong login ID or password."}), 401

        login_id = login_id.strip().lower()
        user_context.set_current_user(login_id, is_guest=False)
        session.clear()
        session["user_id"] = login_id
        session["is_guest"] = False
        session["session_id"] = session_manager.create_session()
        clear_memory()  # every login starts a fresh working-memory session
        return jsonify({"status": "ok", "login_id": login_id})

    @app.route("/api/auth/guest", methods=["POST"])
    def api_auth_guest():
        user_context.set_current_user("guest", is_guest=True)
        session.clear()
        session["user_id"] = "guest"
        session["is_guest"] = True
        session["session_id"] = session_manager.create_session()
        clear_memory()
        return jsonify({"status": "ok", "login_id": "guest", "is_guest": True})

    @app.route("/api/auth/logout", methods=["POST"])
    def api_auth_logout():
        session.clear()
        return jsonify({"status": "ok"})

    @app.route("/api/auth/whoami", methods=["GET"])
    def api_auth_whoami():
        return jsonify({
            "logged_in": bool(session.get("user_id")),
            "login_id": session.get("user_id"),
            "is_guest": session.get("is_guest", False),
        })

    # ---------------- Chat ----------------

    ALLOWED_IMAGE_MIME_TYPES = {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/webp": "webp",
        "image/gif": "gif",
    }
    MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB

    @app.route("/api/chat", methods=["POST"])
    def api_chat():
        image_bytes = None
        image_mime_type = None
        image_saved_url = None

        # Images arrive as multipart/form-data (a real file), plain-text
        # messages keep using JSON like before.
        if request.content_type and "multipart/form-data" in request.content_type:
            caption = (request.form.get("user_message") or "").strip()
            image_file = request.files.get("image")
        else:
            data = request.json or {}
            caption = (data.get("user_message") or "").strip()
            image_file = None

        if image_file and image_file.filename:
            image_mime_type = image_file.mimetype
            if image_mime_type not in ALLOWED_IMAGE_MIME_TYPES:
                return jsonify({
                    "error": "invalid_image",
                    "message": "Unsupported image type. Use PNG, JPEG, WEBP, or GIF."
                }), 400

            image_bytes = image_file.read()
            if len(image_bytes) > MAX_IMAGE_BYTES:
                return jsonify({
                    "error": "image_too_large",
                    "message": "Image is too large (max 10MB)."
                }), 400

            ext = ALLOWED_IMAGE_MIME_TYPES[image_mime_type]
            safe_name = secure_filename(f"{uuid.uuid4().hex}.{ext}")
            save_path = os.path.join(app.config["CHAT_UPLOAD_DIR"], safe_name)
            with open(save_path, "wb") as f:
                f.write(image_bytes)
            image_saved_url = url_for("static", filename=f"uploads/chat/{safe_name}")

        if not caption and not image_bytes:
            return jsonify({"error": "Empty message"}), 400

        # What we actually store in chat history/transcript — keep the image
        # visible on replay via a small marker the frontend knows how to render.
        if image_saved_url:
            history_user_message = f"[image]{image_saved_url}" + (f" {caption}" if caption else "")
        else:
            history_user_message = caption

        # What we send to Gemini as the text portion of this turn.
        prompt_user_message = caption if caption else "[User sent an image with no caption. Describe/respond to the image.]"

        if not has_api_key():
            return jsonify({
                "error": "missing_api_key",
                "message": "No Gemini API key configured yet. Add one in Settings."
            }), 401

        try:
            prompt = build_prompt(prompt_user_message)
            reply = ask_gemini(prompt, image_bytes=image_bytes, image_mime_type=image_mime_type, enable_tools=True)
        except MissingAPIKeyError as e:
            return jsonify({"error": "missing_api_key", "message": str(e)}), 401
        except genai_errors.ClientError as e:
            if getattr(e, "status_code", None) == 429 or "RESOURCE_EXHAUSTED" in str(e):
                return jsonify({
                    "error": "rate_limited",
                    "message": "Gemini free-tier per-minute limit abhi hit ho gayi hai "
                                "(daily quota alag cheez hai — AI Studio dashboard usually "
                                "wahi dikhata hai). Thodi der (30-60 sec) ruk ke dobara try karein, "
                                "ya Settings mein koi doosra model select karein."
                }), 429
            raise

        result = _normalize_reply(reply)
        save_chat(history_user_message, result["response"])

        long_term_context = None
        followup_context = None  # for automation results / task_status
        for command in result["commands"]:
            command_result = execute(command)
            action = command.get("action")

            if action == "review_mem" and command_result:
                long_term_context = get_memory_context_for_prompt(command_result)

            elif action == "task_status" and command_result:
                import json as _json
                followup_context = (
                    "TASK STATUS (from task_manager, JSON):\n"
                    f"{_json.dumps(command_result, ensure_ascii=False)}"
                )

            elif action in AUTOMATION_ACTIONS and command_result:
                import json as _json
                followup_context = (
                    "AUTOMATION RESULT (from command_router, JSON):\n"
                    f"{_json.dumps(command_result, ensure_ascii=False)}"
                )

            elif (
                action in minecraft_manager.ACTION_NAMES
                or action in ("minecraft_mode", "recall_minecraft_memory")
            ) and command_result:
                import json as _json
                followup_context = (
                    "MINECRAFT RESULT (from command_router, JSON):\n"
                    f"{_json.dumps(command_result, ensure_ascii=False)}"
                )

        if long_term_context:
            guided_message = (
                f"{prompt_user_message}\n\n[System Note: Memory has been fetched successfully. "
                f"Answer the user naturally based ONLY on the LONG-TERM MEMORY CONTEXT "
                f"provided above. DO NOT output any <COMMAND> blocks.]"
            )
            memory_prompt = build_prompt(guided_message, long_term_context=long_term_context)
            memory_reply = _safe_ask_gemini(memory_prompt)
            if memory_reply is None:
                response_text = (
                    "Memory mil gayi, but usse explain karte waqt Gemini se connect nahi ho paya. "
                    "Ek baar phir se pooch lena."
                )
                save_chat(f"[Memory Review] {history_user_message}", response_text)
            else:
                memory_result = _normalize_reply(memory_reply)
                response_text = memory_result["response"]
                save_chat(f"[Memory Review] {history_user_message}", memory_result["response"])
        elif followup_context:
            guided_message = (
                f"{prompt_user_message}\n\n[System Note: {followup_context}\n\n"
                f"Tell the user, in your normal personality, what happened (done/pending/failed "
                f"tasks, or the automation result above). DO NOT output any <COMMAND> block.]"
            )
            followup_prompt = build_prompt(guided_message)
            followup_reply = _safe_ask_gemini(followup_prompt)
            if followup_reply is None:
                response_text = (
                    "Kaam ho gaya hoga shayad, but result batate waqt Gemini se error aa gaya. "
                    "Sessions/history check kar lena ya dobara pooch lena."
                )
                save_chat(f"[Task Update] {history_user_message}", response_text)
            else:
                followup_result = _normalize_reply(followup_reply)
                response_text = followup_result["response"]
                save_chat(f"[Task Update] {history_user_message}", followup_result["response"])
        else:
            response_text = result["response"]

        # --- Agentic plan auto-continuation -------------------------------
        # If a create_plan (or update_plan_step) call left an in_progress
        # plan behind, keep driving Gemini through the remaining steps
        # automatically in THIS same request, instead of waiting for the
        # Admin to say "next" after every single step. Capped hard so a
        # confused model can't loop forever burning API calls.
        active_plan = agent_planner.get_plan()
        if active_plan and active_plan.get("status") == "in_progress":
            MAX_PLAN_ITERATIONS = 8
            plan_response_parts = [response_text] if response_text else []

            for _ in range(MAX_PLAN_ITERATIONS):
                current_plan = agent_planner.get_plan()
                if not current_plan or current_plan.get("status") != "in_progress":
                    break

                step_idx = current_plan.get("current_step", 0)
                steps = current_plan.get("steps", [])
                if step_idx < 0 or step_idx >= len(steps):
                    break
                step_text = steps[step_idx]["text"]

                continue_message = (
                    f"[System Note: You have an ACTIVE PLAN — goal: '{current_plan['goal']}'. "
                    f"You are on step {step_idx + 1} of {len(steps)}: \"{step_text}\". "
                    f"Call whichever action(s) complete THIS step now, then call "
                    f"update_plan_step(step_index={step_idx}, status=...) to mark it done, "
                    f"failed, or needs_input. If you need something only the Admin can do "
                    f"(captcha, manual password entry, payment approval), call "
                    f"update_plan_step with needs_input and explain what's needed in your "
                    f"text reply — do NOT guess or fabricate a result. If every step is "
                    f"already done, just tell the Admin the plan is complete.]"
                )
                step_prompt = build_prompt(continue_message)
                time.sleep(2)  # small gap so 8 back-to-back plan steps don't
                                # blow the free-tier per-minute (RPM) limit
                step_reply = _safe_ask_gemini(step_prompt)
                if step_reply is None:
                    # Gemini failed mid-plan. Stop auto-driving here instead
                    # of crashing the whole request — everything generated
                    # in earlier steps this request (in plan_response_parts)
                    # is preserved and still returned to the user, plus a
                    # note that the plan is paused rather than complete.
                    plan_response_parts.append(
                        f"(Step {step_idx + 1} pe Gemini se error aa gaya, plan yahin ruk gaya hai — "
                        f"'continue' bolke dobara try kar sakte ho.)"
                    )
                    save_chat(
                        f"[Plan Step {step_idx + 1}] {step_text}",
                        "(Gemini call failed — plan paused)",
                    )
                    break

                step_result = _normalize_reply(step_reply)

                if step_result["response"]:
                    plan_response_parts.append(step_result["response"])
                save_chat(f"[Plan Step {step_idx + 1}] {step_text}", step_result["response"])

                if not step_result["commands"]:
                    # Model just talked (likely asking a question) — stop
                    # auto-driving and let the Admin reply first.
                    break

                for command in step_result["commands"]:
                    execute(command)

                refreshed = agent_planner.get_plan()
                if not refreshed or refreshed.get("status") != "in_progress":
                    break

            response_text = "\n\n".join(p for p in plan_response_parts if p)

        # Log this exchange to the permanent, session-scoped transcript used
        # for the "recent chats" sidebar (separate from the rolling
        # short_term memory used above for the LLM prompt).
        session_id = session.get("session_id")
        if session_id:
            session_manager.append_message(session_id, history_user_message, response_text)

        # --- Parallel Audio Generation (modular TTS) ---
        audio_urls = []
        try:
            filenames = tts_module.generate_audio_chunks_sync(response_text, app.config["AUDIO_DIR"])
            audio_urls = [url_for("static", filename=f"audio/{fname}") for fname in filenames]
        except Exception as e:
            print(f"[TTS Master Error] {e}")

        return jsonify({
            "response": response_text,
            "audio_urls": audio_urls,
        })

    @app.route("/api/audio/delete", methods=["POST"])
    def api_audio_delete():
        payload = request.get_json(silent=True) or {}
        filenames = payload.get("filenames") or []
        if not isinstance(filenames, list):
            return jsonify({"error": "invalid_request", "message": "Expected a list of filenames."}), 400

        deleted = []
        errors = []
        for filename in filenames:
            if not isinstance(filename, str) or not re.fullmatch(r"resp_\d+_\d+\.mp3", filename):
                errors.append({"filename": filename, "reason": "invalid_filename"})
                continue

            file_path = os.path.join(app.config["AUDIO_DIR"], filename)
            if not os.path.exists(file_path):
                errors.append({"filename": filename, "reason": "not_found"})
                continue

            try:
                os.remove(file_path)
                deleted.append(filename)
            except Exception as exc:
                errors.append({"filename": filename, "reason": str(exc)})

        return jsonify({"status": "ok", "deleted": deleted, "errors": errors})

    # ---------------- Resume past session into active working memory ----------------
    @app.route("/api/sessions/resume/<session_id>", methods=["POST"])
    def api_sessions_resume(session_id):
        # Ensure the session belongs to the current user
        messages = session_manager.get_session_messages(session_id)
        if messages is None:
            return jsonify({"error": "not_found", "message": "Session not found."}), 404

        # Set as active session
        session["session_id"] = session_id

        # Replace rolling short-term memory with the transcript so the user can continue
        try:
            from backend.memory_manager.short_term import clear_memory, save_chat
            clear_memory()
            for m in messages:
                save_chat(m.get('user', ''), m.get('arika', ''))
        except Exception as e:
            print(f"[resume] failed to load transcript into short-term: {e}")

        return jsonify({"status": "ok", "session_id": session_id})

    # ---------------- History (legacy flat view, kept for compatibility) ----------------

    @app.route("/api/history", methods=["GET"])
    def api_history():
        """Rolling working-memory history for the CURRENT session only (not
        just the last 10 used in the LLM prompt window)."""
        limit = request.args.get("limit", type=int)
        messages = load_messages()
        if limit:
            messages = messages[-limit:]
        return jsonify({"history": messages})

    # ---------------- Sessions ("recent chats" sidebar) ----------------

    @app.route("/api/sessions", methods=["GET"])
    def api_sessions_list():
        return jsonify({
            "sessions": session_manager.list_sessions(),
            "active_session_id": session.get("session_id"),
        })

    @app.route("/api/sessions/new", methods=["POST"])
    def api_sessions_new():
        """'New chat' button — starts a fresh session and clears the
        rolling working memory, without logging the user out."""
        session["session_id"] = session_manager.create_session()
        clear_memory()
        return jsonify({"status": "ok", "session_id": session["session_id"]})

    @app.route("/api/sessions/<session_id>", methods=["GET"])
    def api_sessions_get(session_id):
        """Read-only view of a past session's transcript. Returns 404 if the
        session doesn't exist or doesn't belong to the current user/guest."""
        messages = session_manager.get_session_messages(session_id)
        if messages is None:
            return jsonify({"error": "not_found", "message": "Session not found."}), 404
        return jsonify({
            "session_id": session_id,
            "messages": messages,
            "is_active": session_id == session.get("session_id"),
        })

    @app.route("/api/sessions/delete/<session_id>", methods=["POST"])
    def api_sessions_delete(session_id):
        """Delete a past session (transcript + index entry)."""
        success = session_manager.delete_session(session_id)
        if not success:
            return jsonify({"error": "not_found_or_forbidden", "message": "Session not found or not owned by you."}), 404
        # If it was the active session, clear it
        if session.get("session_id") == session_id:
            # Start a new empty session id but do NOT clear the user's rolling
            # short-term memory. Deleting a saved transcript should not remove
            # the current LLM working memory (short_term.json).
            session["session_id"] = session_manager.create_session()
        return jsonify({"status": "ok", "session_id": session_id})

    # ---------------- Settings ----------------

    @app.route("/api/settings", methods=["GET"])
    def api_settings_get():
        settings = dict(settings_manager.load_settings())
        has_email_password = bool(settings.pop("email_app_password", ""))
        return jsonify({
            "settings": settings,
            "has_email_password": has_email_password,
            "available_tts_voices": settings_manager.AVAILABLE_TTS_VOICES,
            "available_gemini_models": settings_manager.AVAILABLE_GEMINI_MODELS,
            "has_api_key": has_api_key(),
        })

    @app.route("/api/settings", methods=["POST"])
    def api_settings_post():
        data = request.json or {}

        allowed_keys = {
            "tts_voice", "wake_word", "stt_lang", "gemini_model",
            "show_avatar", "phone_adb_address", "email_address",
            "email_app_password", "browser_debug_port",
            "minecraft_host", "minecraft_port", "minecraft_username", "minecraft_auth",
        }
        new_settings = {k: v for k, v in data.get("settings", {}).items() if k in allowed_keys}
        # Blank password field means "keep what's already saved", same as
        # the Gemini API key field — never overwrite a real secret with "".
        if not new_settings.get("email_app_password"):
            new_settings.pop("email_app_password", None)

        updated = settings_manager.save_settings(new_settings) if new_settings else settings_manager.load_settings()

        return jsonify({"status": "ok", "settings": updated})

    @app.route("/api/settings/api-key", methods=["POST"])
    def api_settings_api_key():
        data = request.json or {}
        api_key = (data.get("api_key") or "").strip()
        if not api_key:
            return jsonify({"status": "error", "message": "API key is required"}), 400

        try:
            save_api_key(api_key)
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)}), 400

        return jsonify({"status": "ok"})

    @app.route("/api/settings/api-key/status", methods=["GET"])
    def api_settings_api_key_status():
        return jsonify({"has_api_key": has_api_key()})

    @app.route("/api/minecraft/status", methods=["GET"])
    def api_minecraft_status():
        return jsonify({
            "minecraft_mode": minecraft_manager.is_active(),
            "status": minecraft_manager.get_compact_status(),
        })

    @app.route("/api/minecraft/awareness", methods=["GET"])
    def api_minecraft_awareness():
        """Polled by the frontend every few seconds while Minecraft mode is
        active — returns a proactive comment if the background awareness
        check (backend/minecraft_awareness.py) has generated one since the
        last poll, or has_message: false otherwise (the normal case)."""
        msg = minecraft_awareness.pop_pending()
        if not msg:
            return jsonify({"has_message": False})
        return jsonify({
            "has_message": True,
            "response": msg["text"],
            "audio_urls": msg["audio_urls"],
        })

    @app.route("/api/minecraft/mode", methods=["POST"])
    def api_minecraft_mode():
        # Same Admin-only gate as every other real-world action (see
        # command_router.execute's minecraft action handling).
        if not admin_manager.is_admin():
            return jsonify({"status": "error", "message": "Admin only."}), 403
        data = request.json or {}
        active = bool(data.get("active", False))
        connect = None
        if active and (data.get("host") or data.get("username") or data.get("port")):
            connect = {
                "host": data.get("host"),
                "port": data.get("port"),
                "username": data.get("username"),
            }
        result = minecraft_manager.set_mode(active, connect=connect)
        return jsonify(result)

    @app.route("/api/plan", methods=["GET"])
    def api_plan_get():
        """Polled by the frontend's Todo List widget every couple seconds
        while a plan is active — returns the plan.json snapshot as-is."""
        return jsonify(agent_planner.summary())

    @app.route("/api/plan/cancel", methods=["POST"])
    def api_plan_cancel():
        if not admin_manager.is_admin():
            return jsonify({"status": "error", "message": "Admin only."}), 403
        agent_planner.cancel_plan()
        return jsonify({"status": "ok"})

    @app.route("/api/profile/delete", methods=["POST"])
    def api_profile_delete():
        from backend.memory_manager.profile import delete_profile
        success = delete_profile()
        if not success:
            return jsonify({"error": "not_found", "message": "Profile not found or could not be deleted."}), 404
        return jsonify({"status": "ok"})

    return app
