"""GIT_ASKPASS helper for the dual-bridge worker (companion to codex_adapter).

git invokes this with the credential prompt as argv[1] (e.g. "Username for
'https://github.com': " or "Password for 'https://user@github.com': ") and reads
the answer from stdout. We answer from a small store file whose path arrives via
the GIT_BRIDGE_CREDFILE env var -- the token therefore never sits on a command
line (no ps/tasklist leak) and never passes through a shell (no injection,
regardless of token contents). The store file holds ONE line in git's
credential-store format:

    https://<urlencoded-user>:<urlencoded-token>@<host>

Why GIT_ASKPASS and not `credential.helper=store --file=...`: the inline store
helper is run via sh (git-bash) on Windows, where a Windows path in --file= is
unreadable and git silently falls back to an interactive /dev/tty prompt
("could not read Username", global rule §10.3). GIT_ASKPASS is exec'd directly by
git with no shell in between, so it is path- and quoting-safe on Windows.

Pure stdlib; safe to run under the hardened safe_subprocess_env (PYTHON* allowed).
"""
from __future__ import annotations

import os
import sys
import urllib.parse


def _read_user_token(path: str) -> tuple[str, str]:
    """Parse the one-line credential-store file -> (decoded_user, decoded_token).
    Returns ("", "") on any problem (git then prompts / fails, never crashes)."""
    try:
        with open(path, encoding="utf-8") as fh:
            line = fh.readline().strip()
    except OSError:
        return "", ""
    # Format: <proto>://<user>:<token>@<host>
    if "://" not in line or "@" not in line:
        return "", ""
    after = line.split("://", 1)[1]
    userinfo = after.rsplit("@", 1)[0]
    if ":" not in userinfo:
        return "", ""
    user_enc, _, token_enc = userinfo.partition(":")
    return urllib.parse.unquote(user_enc), urllib.parse.unquote(token_enc)


def main() -> int:
    prompt = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    user, token = _read_user_token(os.environ.get("GIT_BRIDGE_CREDFILE", ""))
    # git asks for the username first, then the password; answer the matching one.
    if "username" in prompt:
        sys.stdout.write(user + "\n")
    else:
        sys.stdout.write(token + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
