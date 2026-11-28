"""draft_email (never sends) and run_python (disabled by default; NOT a security sandbox)."""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile

from birds.harness.guard import ToolError

_ADDRESS = re.compile(r"[^@\s<>,;\"']+@[^@\s<>,;\"']+\.[^@\s<>,;\"'.]+")


def recipients(to: list) -> tuple[list[str], str]:
    """(email addresses, the rest): 'Marc Petit' is not an address, so it is shown as a name to complete instead
    of ending up in the mailto: link. 'Marc <marc@x.fr>' keeps its address."""
    addresses, names = [], []
    for item in to or []:
        text = " ".join(str(item).split())
        m = _ADDRESS.search(text)
        if m and m.group(0) not in addresses:
            addresses.append(m.group(0))
        elif text and not m:
            names.append(text)
    return addresses, ", ".join(names)


def given_by_user(address: str, ctx) -> bool:
    """An address someone wrote: the user (this message, an earlier one, a document they attached) or a page read
    for this request (a contact page; a tainted run asks the user to confirm, guard.py). Never one the model made up:
    « proprietaire@email.com » for « mon propriétaire » is not an address anyone gave."""
    seen = " ".join([ctx.said, ctx.request, ctx.message, *(text for _kind, text in ctx.fetched)])
    return re.search(rf"(?<![\w.+-]){re.escape(address)}(?![\w-])", seen, re.I) is not None


def draft_email(args: dict, ctx) -> str:
    to, hint = recipients(list(args["to"]))
    made_up = [a for a in to if not given_by_user(a, ctx)]
    to = [a for a in to if a not in made_up]
    draft = {"to": to, "subject": args["subject"], "body": args["body"], "tone": args.get("tone") or "neutral"}
    if hint:
        draft["to_hint"] = hint  # shown on the card as a recipient to complete
    ctx.drafts.append(draft)  # shown by the UI; the harness has no way to send mail
    missing = f" Recipient to be completed by the user: {hint}." if hint else ""
    if made_up:
        missing += (
            f" Removed {', '.join(made_up)}: the user never gave this address. The card asks the user to add the "
            "address; do not write any address yourself."
        )
    return (
        "Draft saved and shown to the user as a card with copy buttons and an open-in-mail-app link (not sent). "
        "You cannot send emails: never offer to send it. Do not repeat the body; say in one sentence that it is "
        f"ready to review. To: {', '.join(to) or '(none)'}.{missing} Subject: {draft['subject']}"
    )


def _limits(cpu_s: int):
    def apply():  # runs in the child just before exec
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s + 1))
        resource.setrlimit(resource.RLIMIT_FSIZE, (10_000_000, 10_000_000))
        resource.setrlimit(resource.RLIMIT_AS, (2_000_000_000, 2_000_000_000))

    return apply


def run_python(args: dict, ctx) -> str:
    cfg = ctx.config
    if not cfg.allow_python:
        raise ToolError(
            "run_python is not enabled on this deployment. Do the calculation directly, or say that code execution is unavailable."
        )
    with tempfile.TemporaryDirectory(prefix="bird_py_") as tmp:
        # -I: isolated mode (no user site, no PYTHON* variables, no cwd on sys.path). The environment is emptied so
        # no token, proxy setting or credential of the host process is handed to the code. This is hygiene, not
        # isolation: the code still runs as the same user and can open files and sockets.
        try:
            p = subprocess.run(
                [sys.executable, "-I", "-c", args["code"]],
                cwd=tmp,
                capture_output=True,
                text=True,
                timeout=cfg.python_wall_s,
                env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": tmp},
                stdin=subprocess.DEVNULL,
                preexec_fn=_limits(cfg.python_cpu_s),
            )
        except subprocess.TimeoutExpired:
            raise ToolError(f"the code ran longer than {cfg.python_wall_s:g} s and was stopped") from None
    out = p.stdout[-4000:]
    if p.returncode != 0:
        out += f"\n[exit code {p.returncode}]\n" + p.stderr[-1500:]
    return out.strip() or "(no output)"
