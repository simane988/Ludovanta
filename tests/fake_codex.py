"""Stand-in for the Codex CLI ('codex exec ...') in tests. Behaviour is chosen by the FAKE_CODEX_MODE env var."""
import os
import re
import sys
from pathlib import Path


def arg(args, *names):
    for name in names:
        if name in args:
            return args[args.index(name) + 1]
    return None


def main():
    args = sys.argv[1:]
    print("fake codex args: " + " | ".join(args))
    mode = os.environ.get("FAKE_CODEX_MODE", "task")
    if mode == "fail":
        print("ERROR: not logged in, run 'codex login'")
        return 1
    root = Path(arg(args, "--cd", "-C"))
    result = arg(args, "--output-last-message", "-o")
    prompt_rel = re.search(r"Read the file (\S+) in this project", args[-1]).group(1)
    prompt = (root / prompt_rel).read_text(encoding="utf-8")
    if mode == "image":
        out = re.search(r"`([^`]+)`", prompt).group(1)
        (root / out).write_bytes(b"\x89PNG\r\n\x1a\n" + b"fake")
        report = f"Saved {out}"
    elif mode == "silent":
        report = "I could not generate the image."
    else:
        task = re.search(r"TASK BRIEF (T-\d+)", prompt).group(1)
        card = root / "plan" / "tasks" / f"{task}.md"
        card.write_text(re.sub(r"status: \S+", "status: review", card.read_text(encoding="utf-8"), count=1),
                        encoding="utf-8")
        (root / "Assets" / "FromCodex.cs").write_text("class FromCodex {}\n", encoding="utf-8")
        report = f"What changed: {task} done by fake codex\nagent rule seen: {'--agent codex' in prompt}"
    Path(result).write_text(report + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
