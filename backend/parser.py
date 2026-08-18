import json
import re


def process(response):

    pattern = r"<\s*COMMAND\s*>(.*?)<\s*/\s*COMMAND\s*>"

    commands = []

    matches = re.findall(
        pattern,
        response,
        flags=re.DOTALL | re.IGNORECASE
    )

    for command_text in matches:

        try:
            command = json.loads(command_text.strip())
            commands.append(command)

        except json.JSONDecodeError:
            print("[Parser] Invalid JSON Command")

    clean_response = re.sub(
        pattern,
        "",
        response,
        flags=re.DOTALL | re.IGNORECASE
    ).strip()

    return {
        "response": clean_response,
        "commands": commands
    }
    