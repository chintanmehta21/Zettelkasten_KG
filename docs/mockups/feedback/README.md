# Feedback button — design mockups

Mockups for the "Report Issue / Suggestion" footer button + popup. **No production code is touched in this PR yet.** These pages exist so the visual + interaction design can be reviewed and adjusted before any of it lands in `website/footer/`, `website/static/`, `website/mobile/`, or `website/api/`.

Each file is a self-contained HTML page (inline CSS + JS) that mirrors the live site's design tokens from [`website/static/css/style.css`](../../../website/static/css/style.css). They render correctly when opened directly from disk (`file://`) or via [raw.githack.com](https://raw.githack.com/) for GitHub raw URLs.

---

## Files

| File | What it demonstrates |
|---|---|
| [`desktop.html`](desktop.html) | The recommended desktop experience end-to-end: footer megaphone trigger → modal popup with segmented control, Subject, Description, drag-drop screenshots, follow-up checkbox, privacy notice, success state. Includes a live "Slack preview" pane on the right showing the Block Kit message that would be sent. |
| [`mobile.html`](mobile.html) | The recommended mobile experience: megaphone in `.m-footer`, popup converts to a **bottom sheet** (NN/G + Material 3 guidance) with swipe-down dismiss + full-width Submit pinned above the safe-area. |
| [`icons.html`](icons.html) | Side-by-side comparison of six candidate footer-trigger icons (megaphone, comment-square, bug, flag, exclamation, lightbulb) — pick one. |
| [`selector-variants.html`](selector-variants.html) | Same form rendered three ways for the Issue/Suggestion type selector: horizontal tabs (user's original wording), segmented control (NN/G + Atlassian recommendation), and a `<select>` dropdown. |

---

## Research-grounded design decisions baked in

These are the defaults shown in the mockups. Every one is challenge-able in the PR — change the mockup and we'll adjust.

| Decision | What's in the mockup | Source |
|---|---|---|
| **Footer-trigger icon** | Megaphone (Lucide) at the right end of the existing `.footer` icon row | [Lucide tags `megaphone` as "announcement, attention"](https://lucide.dev/icons/megaphone) — closest semantic match for "issue or suggestion"; NN/G shows icon-only triggers underperform icon+tooltip |
| **Selector pattern** | Segmented control (Issue / Suggestion) inside the modal, not tabs | NN/G: "[Tabs are for distinct content views](https://www.nngroup.com/articles/tabs-used-right/)"; Atlassian: "[Segmented control filters or alters presentation within the existing view](https://atlassian.design/components/tabs/)". Bug vs Suggestion is same form, one attribute → segmented control. **User said "tabs" originally — [selector-variants.html](selector-variants.html) shows all three so you can pick.** |
| **Required fields** | Subject + Description both required, screenshots optional | NN/G: ["Mark all required fields explicitly with an asterisk"](https://www.nngroup.com/articles/required-fields/) |
| **Screenshot UX** | Drag-drop + file picker + paste-from-clipboard, max 3 images, ≤5 MB each post client-side `<canvas>` compression | Sentry / Linear (via Userback) / Vercel widget conventions |
| **Submit confirmation** | Inline success state inside the modal ("Thanks — sent to the team — `FB-7K3Q`") then close, no toast | Vercel Geist Feedback pattern; toasts often miss screen-readers per a11y research |
| **Mobile surface** | Bottom sheet, not centered modal | NN/G [Bottom Sheet](https://www.nngroup.com/articles/bottom-sheet/); Material 3; Vercel explicitly says their feedback widget is desktop-only because mobile needs a different surface |
| **Identity carried to Slack** | Full name (from `_resolve_full_name()`) + Country (`India — IN` format) + Feedback ID (`FB-7K3Q`) | Matches the user's spec; feedback ID enables GDPR Art. 17 erasure mapping back to a DB row |
| **Country source** | User's profile country if set, else `cf-ipcountry` labelled "(approx.)" | GDPR Art. 5(1)(d) accuracy principle: prefer user-stated to IP-derived for non-essential purposes |
| **Email follow-up** | Explicit opt-in checkbox, **unchecked by default** | Sentry User Feedback widget config defaults `isEmailRequired: false` |
| **Sensitive-info notice** | One-line muted notice above the upload | Industry pattern (Gmail, Qualtrics, Intercom Fin Vision, Userback `usprivacy` class) |
| **Slack delivery** | Bot Token + `chat.postMessage` + `files_upload_v2` + Block Kit `slack_file` | Incoming Webhooks **cannot attach files**; `files.upload` retires **2025-11-12**; `slack_file` keeps images private to the workspace (no signed-URL leakage) |

---

## Open questions before we start wiring production code

Items below are NOT decided in this mockup PR — they need your call before the implementation PR opens.

1. **Selector pattern.** Mockup uses segmented control. Compare via [selector-variants.html](selector-variants.html). Pick one.
2. **Icon.** Mockup uses megaphone. Compare via [icons.html](icons.html). Pick one.
3. **Auth gate.** Mockup currently shows logged-in user identity. Decision needed: require login (recommended — pairs with rate-limit on user ID), or allow anonymous submission with Cloudflare Turnstile gating?
4. **Image storage path.** Mockup assumes `slack_file` (private to Slack workspace, no public URLs). Confirm vs the alternative (Supabase Storage + signed URL in Block Kit `image_url`).
5. **DB persistence.** Mockup's success message includes a Feedback ID `FB-7K3Q`. To make that ID useful (GDPR erasure, status follow-up, retroactive triage), we need a `content.user_feedback` row per submission. Confirm yes/no.
6. **Slack workspace + bot install.** A new Slack-app install with `chat:write` + `files:write` scopes is required. Need: (a) target workspace ID, (b) confirmation that `#zk-testing` exists there, (c) operator to install the app and paste the bot token into `/etc/secrets/api_env` as `SLACK_BOT_TOKEN_FEEDBACK`.
7. **Rate limits.** Mockup assumes 5/min and 20/hour per user, 10/min per IP. Confirm or adjust.
8. **Privacy policy disclosure.** Research recommends adding Slack to the sub-processor list (Trust Center / DPA Exhibit B), not naming it in the public privacy policy. Confirm policy-update path.

---

## What comes next

1. You review these mockups + answer the 8 open questions above (in the PR thread or in chat).
2. I write the design spec at `docs/superpowers/specs/2026-05-27-feedback-button-design.md` reflecting your decisions.
3. The brainstorming skill hands off to `superpowers:writing-plans` for the implementation plan.
4. Implementation PR (separate from this mockup PR) follows the plan with TDD per the project's execution discipline.

The mockup pages don't ship to production. They exist only for design review and will be removed before the implementation PR merges (or moved to `docs/superpowers/specs/` as reference attachments).
