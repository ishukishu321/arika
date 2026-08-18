import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend import gemini
from backend.gemini import ask_gemini
from backend.prompt_builder import build_prompt
from backend.parser import process
from backend.command_router import execute
from backend.memory_manager.short_term import save_chat, clear_memory
from backend.memory_manager.long_term_mem_manager import get_memory_context_for_prompt
from backend.memory_manager import session_manager
from backend import auth_manager
from backend import user_context


def _ensure_api_key_interactive():
    """Only the CLI is allowed to block on input() for the API key.
    The web app instead prompts through the Settings panel."""
    if gemini.has_api_key():
        return
    api_key = input("Enter your Gemini API key: ").strip()
    if not api_key:
        raise ValueError("Gemini API key is required.")
    gemini.save_api_key(api_key)
    print(f"Saved Gemini API key to {gemini.API_KEY_FILE}")


def _login_interactive():
    """Ask for login_id/password (or guest mode) before starting the chat
    loop, and set the user context so every memory file resolves to the
    right person's folder."""
    print("=== Arika login ===")
    print("1) Log in")
    print("2) Create account")
    print("3) Continue as guest")
    choice = input("Choose 1/2/3: ").strip()

    if choice == "3":
        user_context.set_current_user("guest", is_guest=True)
        print("\n[Guest mode] Nothing here will be saved to any account.\n")
        return "guest", True

    login_id = input("Login ID: ").strip()
    password = input("Password: ").strip()

    if choice == "2":
        try:
            auth_manager.register_user(login_id, password)
        except ValueError as e:
            print(f"[Error] {e}")
            return _login_interactive()
        print(f"\nAccount '{login_id.lower()}' created.\n")
    else:
        if not auth_manager.verify_user(login_id, password):
            print("[Error] Wrong login ID or password.\n")
            return _login_interactive()
        print(f"\nWelcome back, {login_id.lower()}.\n")

    user_context.set_current_user(login_id.lower(), is_guest=False)
    return login_id.lower(), False


def main():
    print("=== Arika AI Assistant (CLI) ===")
    print("Type 'exit' to quit.\n")

    login_id, is_guest = _login_interactive()

    from backend import calendar_manager
    calendar_manager.start_background_checker()

    # Every login (like the web app) starts a brand-new session and clears
    # the rolling working memory — past chats stay saved, just not fed
    # straight back into this new conversation's context.
    session_id = session_manager.create_session()
    clear_memory()

    _ensure_api_key_interactive()

    while True:
        user = input("You : ").strip()

        if not user:
            continue

        if user.lower() == "exit":
            print("\nArika : Bye! \U0001F44B")
            break

        try:
            prompt = build_prompt(user)
            reply = ask_gemini(prompt, enable_tools=True)
            legacy = process(reply["text"])
            result = {
                "response": legacy["response"],
                "commands": reply["commands"] + legacy["commands"],
            }

            save_chat(user, result["response"])
            session_manager.append_message(session_id, user, result["response"])
            print(f"\nArika : {result['response']}\n")

            long_term_context = None
            for command in result["commands"]:
                command_result = execute(command)
                if command.get("action") == "review_mem" and command_result:
                    long_term_context = get_memory_context_for_prompt(command_result)

            if long_term_context:
                print("\n[Memory search result processing...]\n")
                guided_message = (
                    f"{user}\n\n[System Note: Memory has been fetched successfully. "
                    f"Answer the user naturally based ONLY on the LONG-TERM MEMORY CONTEXT "
                    f"provided above. DO NOT output any <COMMAND> blocks.]"
                )
                memory_prompt = build_prompt(guided_message, long_term_context=long_term_context)
                memory_reply = ask_gemini(memory_prompt, enable_tools=True)
                memory_legacy = process(memory_reply["text"])
                memory_result = {
                    "response": memory_legacy["response"],
                    "commands": memory_reply["commands"] + memory_legacy["commands"],
                }
                print(f"Arika (from memory): {memory_result['response']}\n")
                save_chat(f"[Memory Review] {user}", memory_result["response"])
                session_manager.append_message(session_id, f"[Memory Review] {user}", memory_result["response"])

        except Exception as e:
            print(f"\n[Error] {e}\n")


if __name__ == "__main__":
    main()
