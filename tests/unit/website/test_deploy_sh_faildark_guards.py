"""2026-08-01: guards for the fail-DARK class that caused the 2026-07-31 outage.

`deploy.sh` stops AND `docker rm`s the serving container before starting the new
colour (forced by RAM: 2 GB cannot hold two containers each carrying the 267 MB
int8 reranker). Everything between that removal and the Caddy flip therefore
runs with NOTHING serving. A gate that aborts in that window leaves Caddy
pointed at a container that no longer exists — raw 502s until a human notices.

The smoke gate was fixed first; these tests exist because the cgroup and stage2
asserts sit in the SAME window and fire EARLIER, so they would have tripped
before the smoke fail-safe was ever reached.
"""
from __future__ import annotations

import re
from pathlib import Path

OPS = Path(__file__).resolve().parents[3] / "ops" / "deploy"
DEPLOY_SH = OPS / "deploy.sh"
ROLLBACK_SH = OPS / "rollback.sh"


def _deploy() -> str:
    return DEPLOY_SH.read_text(encoding="utf-8")


def _code_only(text: str) -> str:
    """Strip comment lines so ordering assertions test code, not prose.

    Without this, a comment reading "capture logs BEFORE docker rm" matches
    before the real `docker rm` and inverts the check.
    """
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def _dark_window(text: str) -> str:
    """The span where nothing is serving: ACTIVE removed -> Caddy flipped."""
    start = text.index('docker rm "$ACTIVE_CONTAINER_NAME_PRE"')
    end = text.index("Flipping Caddy upstream", start)
    return text[start:end]


def test_failsafe_defined_before_the_point_of_no_return():
    """restore_previous_color must be in scope for every gate in the window."""
    text = _deploy()
    assert text.index("restore_previous_color() {") < text.index("maint_window open"), (
        "restore_previous_color is defined after the cutover begins, so the "
        "earlier asserts cannot call it."
    )


def test_every_fatal_exit_in_the_dark_window_restores_service():
    """No abort between container removal and the flip may leave the site dark."""
    window = _code_only(_dark_window(_deploy()))
    exits = re.findall(r"^\s*exit (\d+)$", window, re.M)
    assert exits, "expected fatal exits inside the dark window"
    for code in exits:
        # Find the exit and confirm restore_previous_color precedes it closely.
        idx = window.index(f"exit {code}")
        preceding = window[max(0, idx - 600):idx]
        assert "restore_previous_color" in preceding, (
            f"exit {code} aborts inside the dark window without restoring "
            f"service — this is the 2026-07-31 outage shape."
        )


def test_cgroup_and_stage2_asserts_specifically_restore():
    """These two fired before the smoke gate and were missed in the first fix."""
    window = _dark_window(_deploy())
    for code, gate in (("87", "cgroup-assert"), ("88", "stage2-assert")):
        assert f'restore_previous_color "{gate}"' in window, (
            f"{gate} (exit {code}) must restore the previous colour"
        )


def test_stale_false_comments_removed():
    """The old abort text made two claims that the sequential rewrite falsified."""
    text = _deploy()
    assert "Caddy still on previous color" not in text, (
        "false: that colour's container is docker rm'd before these gates run"
    )
    assert "--force-recreate will replace it" not in text, (
        "false: the deploy uses `up -d --no-deps` with no --force-recreate"
    )


def test_caddy_smoke_deliberately_does_not_restore():
    """exit 90 is post-flip: the new colour is healthy and Caddy is the fault.

    Tearing down a verified-good container there would remove the only working
    backend, so the omission must stay deliberate and documented.
    """
    text = _deploy()
    assert "deliberately does NOT call restore_previous_color" in text
    code = _code_only(text)
    tail = code[code.index("[caddy-smoke] FATAL"):]
    block = tail[: tail.index("exit 90")]
    assert "restore_previous_color" not in block


def test_failsafe_captures_logs_before_removing_container():
    """A safety net that destroys the evidence is worse than none.

    The first version of restore_previous_color ran `docker rm` immediately,
    which erased the only record of why the gate failed — the 2026-08-01T04:08Z
    smoke failure could not be root-caused for exactly this reason.
    """
    code = _code_only(_deploy())
    fn = code[code.index("restore_previous_color() {"):]
    fn = fn[: fn.index("\n}\n")]
    assert "docker logs" in fn
    assert fn.index("docker logs") < fn.index("docker rm"), (
        "logs must be captured before the container is removed"
    )


def test_rollback_pins_last_known_good_image():
    """rollback.sh must not resolve to :latest, which is the new suspect build."""
    deploy = _deploy()
    rollback = ROLLBACK_SH.read_text(encoding="utf-8")

    assert 'echo "$SHA" > "$ROOT/LAST_GOOD_SHA"' in deploy, (
        "deploy.sh must record the SHA that passed every gate"
    )
    assert deploy.index("[caddy-smoke] public probe via Caddy OK") < deploy.index(
        "LAST_GOOD_SHA"
    ), "LAST_GOOD_SHA must only be written on the success path"

    assert "LAST_GOOD_SHA" in rollback
    assert 'IMAGE_TAG="$ROLLBACK_TAG" docker compose' in rollback, (
        "rollback must pass an explicit tag, not fall through to :latest"
    )
    # The compose-up must not swallow failures any more.
    up = rollback[rollback.index('IMAGE_TAG="$ROLLBACK_TAG" docker compose'):]
    up = up[: up.index("\n\n")]
    assert "|| true" not in up, "a failed rollback pull must surface immediately"
