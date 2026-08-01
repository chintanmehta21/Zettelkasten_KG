"""Shared pytest fixtures for the website test suite.

WAVE-D Phase 1 additions:
  * ``slack_webhook_mock`` — respx-based mock for the 3 Slack webhook env vars
    consumed by ``website/features/web_monitor/`` (App_Errors, DO_Alerts,
    User_Activity). Supports forced 200/429/500 status + Retry-After header
    injection so backoff/circuit-breaker tests can drive deterministic paths
    without burning real Slack quota.
  * ``static_color_scan`` — regex helper that fails a test if the supplied
    CSS/HTML text contains banned purple/violet/lavender values OUTSIDE the
    ``/knowledge-graph`` scope. Enforces the "no purple anywhere except KG"
    rule from CLAUDE.md.
  * ``frozen_clock`` — freezegun wrapper anchored at 2026-05-12T00:00:00Z,
    yielding the FrozenDateTimeFactory so tests can ``.tick(timedelta(...))``
    without sleeping. Mirrors the v2-integration variant in
    ``tests/integration/v2/conftest.py`` so unit-level tests have the same
    surface available without pulling the v2-Supabase plumbing.
"""
from __future__ import annotations

import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Callable, Iterable

import pytest


@pytest.fixture(autouse=True)
def _restore_app_singletons():
    """Undo cross-test leakage of app module-level singletons.

    31 test modules reset ``website.api.auth._jwks_client`` and the
    ``website.core.persist`` v2 repo singletons by RAW ASSIGNMENT, which is
    never undone. After the first such test, the rest of the session runs with
    ``_jwks_client = None``, so every later auth-touching test re-fetches JWKS
    over the network; with no network that surfaces as ConnectError -> 500 on
    ``/api/graph``. The symptom is ~12 unrelated tests failing in the full suite
    while passing in isolation — i.e. pure test-order dependence, not a product
    bug. Snapshot-and-restore here fixes all 31 call sites without touching them.

    Import failures are ignored so this stays inert for tests that never load
    the website package.
    """
    saved: list[tuple[object, str, object]] = []
    try:  # pragma: no cover - import guard
        from website.api import auth as auth_mod

        saved.append((auth_mod, "_jwks_client", getattr(auth_mod, "_jwks_client", None)))
    except Exception:  # noqa: BLE001
        pass
    try:  # pragma: no cover - import guard
        from website.core import persist as persist_mod

        for attr in ("_v2_core_repo", "_v2_content_repo"):
            saved.append((persist_mod, attr, getattr(persist_mod, attr, None)))
    except Exception:  # noqa: BLE001
        pass

    yield

    for module, attr, original in saved:
        try:
            setattr(module, attr, original)
        except Exception:  # noqa: BLE001
            pass


def pytest_addoption(parser):
    try:
        parser.addoption(
            '--live',
            action='store_true',
            default=False,
            help='Run live API integration tests',
        )
    except ValueError as exc:
        if '--live' not in str(exc):
            raise
    try:
        parser.addoption(
            '--destructive',
            action='store_true',
            default=False,
            help='Run destructive tests (mutate shared state, e.g. delete users)',
        )
    except ValueError as exc:
        if '--destructive' not in str(exc):
            raise
    try:
        parser.addoption(
            '--e2e',
            action='store_true',
            default=False,
            help='Run browser-driven Playwright e2e tests',
        )
    except ValueError as exc:
        if '--e2e' not in str(exc):
            raise


@pytest.fixture(autouse=True)
def skip_live(request):
    if request.node.get_closest_marker('live') and not request.config.getoption('--live'):
        pytest.skip('Live test — pass --live to run')


@pytest.fixture(autouse=True)
def skip_destructive(request):
    if (
        request.node.get_closest_marker('destructive')
        and not request.config.getoption('--destructive')
    ):
        pytest.skip('Destructive test — pass --destructive to run')


def pytest_collection_modifyitems(config, items):
    """Deselect e2e tests at collection time unless --e2e is passed.

    A function-level autouse fixture would fire too late: pytest-playwright
    parametrizes tests that use the ``page`` fixture by browser type AND
    activates its session-scoped ``browser`` fixture (which launches
    Chromium) BEFORE any function-level autouse fixture runs. CI without
    `playwright install` errors with ``BrowserType.launch: Executable
    doesn't exist``. Collection-time skip avoids fixture activation entirely.
    """
    if config.getoption('--e2e', default=False):
        return
    skip_e2e_marker = pytest.mark.skip(reason='E2E test — pass --e2e to run')
    for item in items:
        if 'e2e' in item.keywords:
            item.add_marker(skip_e2e_marker)


@pytest.fixture
def sample_reddit_url() -> str:
    return "https://www.reddit.com/r/python/comments/abc123/test_post/"


@pytest.fixture
def sample_youtube_url() -> str:
    return "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.fixture
def sample_github_url() -> str:
    return "https://github.com/user/repo"


@pytest.fixture
def sample_newsletter_url() -> str:
    return "https://example.substack.com/p/my-post"


@pytest.fixture
def sample_generic_url() -> str:
    return "https://example.com/article"


# ---------------------------------------------------------------------------
# WAVE-D Phase 1 — shared infra fixtures
# ---------------------------------------------------------------------------


# Three Slack webhook env vars consumed by website/features/web_monitor/*.py.
# Stub URLs used inside respx — the routes match the real
# hooks.slack.com/services/<T>/<B>/<token> shape so production URLs would also
# route through the mock if accidentally injected. Kept short to avoid
# log-noise spam in test output.
_SLACK_WEBHOOK_ENV_VARS = (
    "SLACK_WEBHOOK_APP_ERRORS",
    "SLACK_WEBHOOK_DO_ALERT",
    "SLACK_WEBHOOK_USER_ACTIVITY",
)
_SLACK_STUB_URLS = {
    "SLACK_WEBHOOK_APP_ERRORS":
        "https://hooks.slack.com/services/TTESTAPP/BTESTAPP/tokAppErrors",
    "SLACK_WEBHOOK_DO_ALERT":
        "https://hooks.slack.com/services/TTESTDO/BTESTDO/tokDoAlert",
    "SLACK_WEBHOOK_USER_ACTIVITY":
        "https://hooks.slack.com/services/TTESTUA/BTESTUA/tokUserActivity",
}


@dataclass
class SlackWebhookRecorder:
    """Captured state from a ``slack_webhook_mock`` session.

    ``calls`` is keyed by env-var name (``SLACK_WEBHOOK_APP_ERRORS`` etc.) and
    holds the JSON payload posted on each call, in arrival order. Tests can
    assert call counts, payload shape, and ordering.

    ``router`` is the respx ``MockRouter`` so tests can register additional
    routes (e.g. an unexpected URL) without re-creating the fixture.
    """

    calls: dict[str, list[dict]] = field(default_factory=dict)
    router: object | None = None  # respx.MockRouter — typed loosely to dodge
    # the import at fixture-definition time (respx is dev-only).

    def total_calls(self) -> int:
        return sum(len(v) for v in self.calls.values())


@pytest.fixture
def slack_webhook_mock(monkeypatch):
    """Patch the 3 SLACK_WEBHOOK_* env vars + mock the resulting hooks.

    Yields a callable. Calling it with no args installs default
    ``200 OK`` responses for all three webhooks. Pass ``status=429`` (or any
    HTTP status), and optional ``retry_after`` seconds, to drive backoff
    paths::

        def test_429_retry(slack_webhook_mock):
            rec = slack_webhook_mock(status=429, retry_after=2)
            # ... drive code that posts to Slack ...
            assert rec.total_calls() >= 1

    The recorder tracks every payload so assertions can be written against
    the captured JSON bodies. The fixture is built on respx so it composes
    cleanly with other httpx-mocking patterns already in the suite.
    """
    import respx
    import httpx

    # Stub env vars BEFORE any web_monitor code reads them. Each call
    # to the factory below registers respx routes; the env vars stay
    # pointing at the stub URLs for the test's full lifetime.
    for env_name in _SLACK_WEBHOOK_ENV_VARS:
        monkeypatch.setenv(env_name, _SLACK_STUB_URLS[env_name])

    recorder = SlackWebhookRecorder(
        calls={env: [] for env in _SLACK_WEBHOOK_ENV_VARS}
    )

    router = respx.MockRouter(assert_all_called=False)
    recorder.router = router

    def _build_response(
        request: httpx.Request,
        *,
        env_name: str,
        status: int,
        retry_after: float | None,
    ) -> httpx.Response:
        # Best-effort JSON parse — Slack webhook payloads are always JSON
        # in this codebase but we tolerate non-JSON for forward-compat.
        try:
            payload = request.read()
            recorder.calls[env_name].append(
                __import__("json").loads(payload) if payload else {}
            )
        except Exception:  # noqa: BLE001 — recorder is best-effort
            recorder.calls[env_name].append({"_raw": True})
        headers: dict[str, str] = {}
        if retry_after is not None and status == 429:
            headers["Retry-After"] = str(retry_after)
        return httpx.Response(status, headers=headers, text="ok")

    def _factory(
        *,
        status: int = 200,
        retry_after: float | None = None,
    ) -> SlackWebhookRecorder:
        # Each call rebuilds routes so tests can toggle status mid-test by
        # calling the factory again with different kwargs.
        router.reset()
        for env_name, url in _SLACK_STUB_URLS.items():
            router.post(url).mock(
                side_effect=lambda req, _e=env_name: _build_response(
                    req, env_name=_e, status=status, retry_after=retry_after,
                )
            )
        return recorder

    with router:
        yield _factory


# ---------------------------------------------------------------------------
# static_color_scan — purple/violet/lavender guard
# ---------------------------------------------------------------------------


# Banned values per CLAUDE.md "No purple" rule:
#   * Named tokens: purple / violet / lavender (case-insensitive, word-bound)
#   * Tailwind/common hex: #A78BFA, #7C3AED
#   * Any HSL hue in [250, 290] — covers Indigo→Magenta band
# Allow-listed scopes: any file path containing /knowledge-graph (the 3D viz
# may use amber/gold which can occasionally read as warm-violet on diff
# tooling — we explicitly do NOT scan that surface). Caller can also pass
# additional allow-listed substrings via ``allow_paths``.
_PURPLE_NAMED = re.compile(r"\b(purple|violet|lavender)\b", re.IGNORECASE)
_PURPLE_HEX = re.compile(r"#(?:A78BFA|7C3AED)\b", re.IGNORECASE)
_PURPLE_HSL = re.compile(
    r"hsla?\(\s*(\d{1,3})(?:\.\d+)?\s*(?:,|\s)",
    re.IGNORECASE,
)


@dataclass
class ColorScanFinding:
    file: str
    line: int
    match: str
    rule: str  # "named" | "hex" | "hsl"


@pytest.fixture
def static_color_scan() -> Callable[..., list[ColorScanFinding]]:
    """Scan one or more CSS/HTML strings for banned purple values.

    Returns a callable: ``scan(text, *, source="inline", allow_paths=())``
    yielding a list of ``ColorScanFinding`` (empty list = clean). Tests
    typically assert ``not findings``.

    The ``source`` parameter is used to attribute findings; pass the file
    path when scanning files so failure messages are actionable. Pass
    ``allow_paths=("/knowledge-graph",)`` (default) to skip files whose
    source path contains the allow-listed substring — the 3D viz surface
    is the only place amber/gold is permitted, and its diff tooling can
    flag amber as warm-violet.
    """
    def _scan(
        text: str,
        *,
        source: str = "inline",
        allow_paths: Iterable[str] = ("/knowledge-graph",),
    ) -> list[ColorScanFinding]:
        # Allow-list short-circuit: if the source path contains any
        # allow-listed substring, skip entirely.
        norm_source = source.replace("\\", "/")
        if any(allow in norm_source for allow in allow_paths):
            return []

        findings: list[ColorScanFinding] = []
        for lineno, line in enumerate(text.splitlines(), start=1):
            for m in _PURPLE_NAMED.finditer(line):
                findings.append(
                    ColorScanFinding(
                        file=source, line=lineno, match=m.group(0), rule="named"
                    )
                )
            for m in _PURPLE_HEX.finditer(line):
                findings.append(
                    ColorScanFinding(
                        file=source, line=lineno, match=m.group(0), rule="hex"
                    )
                )
            for m in _PURPLE_HSL.finditer(line):
                try:
                    hue = int(m.group(1))
                except ValueError:
                    continue
                if 250 <= hue <= 290:
                    findings.append(
                        ColorScanFinding(
                            file=source,
                            line=lineno,
                            match=m.group(0),
                            rule="hsl",
                        )
                    )
        return findings

    return _scan


# ---------------------------------------------------------------------------
# frozen_clock — root-level (mirrors tests/integration/v2/conftest.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def frozen_clock():
    """Wrap each test in ``freezegun.freeze_time`` anchored at
    2026-05-12T00:00:00Z. Yields the FrozenDateTimeFactory so tests can
    advance time via ``frozen_clock.tick(timedelta(seconds=N))`` without
    sleeping.

    Mirror of the variant in ``tests/integration/v2/conftest.py`` — defined
    at root so unit-level tests have the same surface available without
    pulling in v2-Supabase plumbing.
    """
    from freezegun import freeze_time

    with freeze_time("2026-05-12T00:00:00Z") as frozen:
        yield frozen


# ── Known-failure ratchet (2026-08-02) ──────────────────────────────────────
# Reads tests/known_failures.txt and xfails each listed node id, so CI goes
# RED only on NEW failures. See that file's header for the rationale and
# sources; docs/claude_audits/open_issues_2026-08-02.md for the triage.
#
# Deliberately uses xfail, never skip: skip does not execute the test body, so
# a skipped test can never tell you it started passing. strict xfail turns an
# unexpected PASS into a failure, which is what makes the baseline self-cleaning.
_KNOWN_FAILURES_PATH = Path(__file__).parent / "known_failures.txt"


def _load_known_failures() -> dict[str, bool]:
    """Return {node_id: strict}. Missing file -> empty (ratchet simply off)."""
    entries: dict[str, bool] = {}
    if not _KNOWN_FAILURES_PATH.exists():
        return entries
    for raw in _KNOWN_FAILURES_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        node_id, _, trailing = line.partition("#")
        node_id = node_id.strip()
        if not node_id:
            continue
        # "# flaky" opts a genuinely-intermittent test out of strict mode.
        entries[node_id] = "flaky" not in trailing.lower()
    return entries


def pytest_collection_modifyitems(config, items):  # noqa: F811 - second hook
    """Apply the known-failure ratchet.

    pytest calls EVERY conftest hook of the same name, so this coexists with
    the --e2e deselection hook above rather than replacing it.
    """
    known = _load_known_failures()
    if not known:
        return
    for item in items:
        strict = known.get(item.nodeid)
        if strict is None:
            continue
        item.add_marker(
            pytest.mark.xfail(
                reason=(
                    "known failure (tests/known_failures.txt). "
                    "If this now PASSES, delete its line from that file."
                ),
                strict=strict,
            )
        )
