"""draft_email (never sends) and run_python (disabled by default; NOT a security sandbox)."""

from __future__ import annotations

import subprocess
import sys
import tempfile

from birds.harness.guard import ToolError


def draft_email(args: dict, ctx) -> str:
    draft = {
        "to": list(args["to"]),
        "subject": args["subject"],
        "body": args["body"],
        "tone": args.get("tone") or "neutral",
    }
    ctx.drafts.append(draft)  # shown by the UI; the harness has no way to send mail
    return f"Draft saved for the user to review (not sent). To: {', '.join(draft['to'])}. Subject: {draft['subject']}"


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
