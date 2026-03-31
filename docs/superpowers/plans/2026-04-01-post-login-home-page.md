# Post-Login Home Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a post-login dashboard at `/home` with user avatar, zettel vault, KG link, and avatar management — all in the existing dark theme.

**Architecture:** Self-contained feature in `website/features/home/` following existing pattern (own HTML/CSS/JS). Client-side auth check via `/api/me`. One new API endpoint (`PUT /api/me/avatar`). 30 pre-generated DiceBear SVG avatars stored in `website/artifacts/avatars/`.

**Tech Stack:** Python/FastAPI (backend route + API), vanilla HTML/CSS/JS (frontend), Supabase (auth + data), DiceBear API (avatar generation)

**Design Spec:** `docs/superpowers/specs/2026-04-01-post-login-home-page-design.md`

---

### Task 1: Generate 30 DiceBear SVG Avatars

**Files:**
- Create: `ops/scripts/generate_avatars.py`
- Create: `website/artifacts/avatars/avatar_00.svg` through `avatar_29.svg`

- [ ] **Step 1: Create the avatar generation script**

```python
# ops/scripts/generate_avatars.py
"""Download 30 DiceBear SVG avatars for user profile pictures.

Run once: python ops/scripts/generate_avatars.py
"""

import os
import urllib.request

STYLES = [
    "adventurer", "bottts", "fun-emoji", "notionists",
    "thumbs", "big-ears", "lorelei",
]
COUNT = 30
OUTPUT_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "website", "artifacts", "avatars"
)


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for i in range(COUNT):
        style = STYLES[i % len(STYLES)]
        seed = f"zettel_avatar_{i}"
        url = f"https://api.dicebear.com/9.x/{style}/svg?seed={seed}"
        out_path = os.path.join(OUTPUT_DIR, f"avatar_{i:02d}.svg")
        print(f"[{i+1}/{COUNT}] {style} -> avatar_{i:02d}.svg")
        urllib.request.urlretrieve(url, out_path)
    print(f"Done. {COUNT} avatars saved to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the script to generate avatars**

Run: `python ops/scripts/generate_avatars.py`
Expected: 30 SVG files appear in `website/artifacts/avatars/`

- [ ] **Step 3: Verify avatar files exist and are valid SVGs**

Run: `ls website/artifacts/avatars/ | wc -l` — should output `30`
Run: `head -1 website/artifacts/avatars/avatar_00.svg` — should start with `<svg`

- [ ] **Step 4: Commit**

```bash
git add ops/scripts/generate_avatars.py website/artifacts/avatars/
git commit -m "feat: generate 30 DiceBear SVG avatars"
```

---

### Task 2: Add PUT /api/me/avatar Endpoint

**Files:**
- Modify: `website/api/routes.py`
- Modify: `website/core/supabase_kg/repository.py`

- [ ] **Step 1: Add `update_user_avatar` method to KGRepository**

Add this method to the `KGRepository` class in `website/core/supabase_kg/repository.py`, inside the `# ── Users` section after the `get_user_by_render_id` method:

```python
def update_user_avatar(self, render_user_id: str, avatar_url: str) -> KGUser | None:
    """Update a user's avatar URL. Returns updated user or None if not found."""
    resp = (
        self._client.table("kg_users")
        .update({"avatar_url": avatar_url})
        .eq("render_user_id", render_user_id)
        .execute()
    )
    return KGUser(**resp.data[0]) if resp.data else None
```

- [ ] **Step 2: Add the avatar update endpoint to routes.py**

Add these imports and endpoint in `website/api/routes.py`:

After the existing `AvatarUpdateRequest` model (add below `SummarizeRequest`):

```python
class AvatarUpdateRequest(BaseModel):
    avatar_id: int

    @field_validator("avatar_id")
    @classmethod
    def validate_avatar_id(cls, v: int) -> int:
        if not (0 <= v <= 29):
            raise ValueError("avatar_id must be between 0 and 29")
        return v
```

Add the endpoint after the existing `GET /me` endpoint:

```python
@router.put("/me/avatar")
async def update_avatar(
    body: AvatarUpdateRequest,
    user: Annotated[dict, Depends(get_current_user)],
):
    """Update the authenticated user's avatar."""
    avatar_url = f"/artifacts/avatars/avatar_{body.avatar_id:02d}.svg"

    sb = _get_supabase(user_id_override=user["sub"])
    if not sb:
        raise HTTPException(status_code=503, detail="Supabase not configured")

    repo, _ = sb
    updated = repo.update_user_avatar(user["sub"], avatar_url)
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")

    return {"avatar_url": avatar_url}
```

- [ ] **Step 3: Verify the server starts without errors**

Run: `cd /c/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault && python -c "from website.api.routes import router; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add website/api/routes.py website/core/supabase_kg/repository.py
git commit -m "feat: add PUT /api/me/avatar endpoint"
```

---

### Task 3: Add /home Route to FastAPI App

**Files:**
- Modify: `website/app.py`

- [ ] **Step 1: Add HOME_DIR constant and static mounts**

In `website/app.py`, add the `HOME_DIR` constant after the existing directory constants:

```python
HOME_DIR = Path(__file__).parent / "features" / "home"
```

Inside `create_app()`, add static mounts after the auth mounts:

```python
# Home page static assets
app.mount("/home/css", StaticFiles(directory=str(HOME_DIR / "css")), name="home-css")
app.mount("/home/js", StaticFiles(directory=str(HOME_DIR / "js")), name="home-js")
```

- [ ] **Step 2: Add the /home GET route**

Add the route inside `create_app()`, after the `auth_callback` route:

```python
@app.get("/home")
async def home(request: Request):
    if _is_mobile(request):
        return RedirectResponse(url="/m/", status_code=302)
    return FileResponse(str(HOME_DIR / "index.html"))
```

Note: Mobile redirect goes to `/m/` for now (mobile home page is out of scope). The auth guard is handled client-side by `home.js`.

- [ ] **Step 3: Create placeholder directory structure**

Create the directory structure so the static mounts don't fail on app startup:

```bash
mkdir -p website/features/home/css
mkdir -p website/features/home/js
touch website/features/home/css/home.css
touch website/features/home/js/home.js
echo "<!DOCTYPE html><html><body>Home placeholder</body></html>" > website/features/home/index.html
```

- [ ] **Step 4: Verify app starts**

Run: `python -c "from website.app import create_app; app = create_app(); print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add website/app.py website/features/home/
git commit -m "feat: add /home route and feature directory"
```

---

### Task 4: Modify Auth Flow to Redirect to /home After Login

**Files:**
- Modify: `website/features/user_auth/js/auth.js`
- Modify: `website/features/user_auth/callback.html`

- [ ] **Step 1: Update auth.js SIGNED_IN handler**

In `website/features/user_auth/js/auth.js`, modify the `onAuthStateChange` callback inside `init()`. Find this block:

```javascript
_supabaseClient.auth.onAuthStateChange(function (event, session) {
    _currentSession = session;
    updateUI(session);
    if (event === 'SIGNED_IN' && loginModal) {
        closeModal();
    }
});
```

Replace with:

```javascript
_supabaseClient.auth.onAuthStateChange(function (event, session) {
    _currentSession = session;
    updateUI(session);
    if (event === 'SIGNED_IN') {
        if (loginModal) closeModal();
        // Redirect to home page after login (only from landing page)
        if (window.location.pathname === '/') {
            window.location.href = '/home';
        }
    }
});
```

- [ ] **Step 2: Update callback.html default return path**

In `website/features/user_auth/callback.html`, find this line:

```javascript
var returnTo = sessionStorage.getItem('auth_return_to') || '/';
```

Change to:

```javascript
var returnTo = sessionStorage.getItem('auth_return_to') || '/home';
```

- [ ] **Step 3: Update auth.js signInWithProvider to set return_to as /home**

In `website/features/user_auth/js/auth.js`, in the `signInWithProvider` function, find:

```javascript
sessionStorage.setItem('auth_return_to', window.location.pathname);
```

Change to:

```javascript
sessionStorage.setItem('auth_return_to', '/home');
```

- [ ] **Step 4: Commit**

```bash
git add website/features/user_auth/js/auth.js website/features/user_auth/callback.html
git commit -m "feat: redirect to /home after login"
```

---

### Task 5: Build Home Page HTML

**Files:**
- Create: `website/features/home/index.html`

- [ ] **Step 1: Write the complete home page HTML**

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Home — Zettelkasten</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/css/style.css">
    <link rel="stylesheet" href="/home/css/home.css">
    <script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <header class="header">
            <div class="branding">
                <div class="logo">
                    <img src="/artifacts/logo-zettelkasten.svg" alt="" class="logo-icon" width="34" height="34" />
                    <span class="logo-text">Zettelkasten</span>
                </div>
                <p class="tagline">The second brain you were promised!</p>
            </div>
            <div class="header-auth">
                <!-- Avatar + Dropdown (replaces login button) -->
                <div class="home-avatar-wrap" id="avatar-wrap">
                    <button class="home-avatar-btn" id="avatar-btn" title="Account menu">
                        <img class="home-avatar-img" id="avatar-img" src="" alt="User avatar" width="32" height="32" />
                        <span class="home-avatar-fallback" id="avatar-fallback"></span>
                    </button>
                    <div class="home-dropdown" id="avatar-dropdown">
                        <a class="home-dropdown-item" href="#" id="menu-profile">
                            <span class="home-dropdown-icon">&#x1F464;</span>
                            My Profile
                        </a>
                        <a class="home-dropdown-item" href="#home-vault">
                            <span class="home-dropdown-icon">&#x1F4DA;</span>
                            My Zettels
                        </a>
                        <a class="home-dropdown-item" href="#" id="menu-settings">
                            <span class="home-dropdown-icon">&#x2699;</span>
                            Settings
                        </a>
                        <a class="home-dropdown-item" href="/knowledge-graph">
                            <span class="home-dropdown-icon">&#x2139;</span>
                            About
                        </a>
                        <div class="home-dropdown-divider"></div>
                        <button class="home-dropdown-item home-dropdown-signout" id="menu-signout">
                            <span class="home-dropdown-icon">&#x23FB;</span>
                            Sign out
                        </button>
                    </div>
                </div>
            </div>
        </header>

        <main class="main">
            <!-- Welcome -->
            <div class="home-welcome" id="home-welcome">
                <h1 class="home-welcome-text">Welcome back, <span id="user-display-name">User</span></h1>
            </div>

            <!-- My Zettels Vault -->
            <section class="home-vault" id="home-vault">
                <div class="home-vault-header">
                    <div class="home-vault-title-row">
                        <h2 class="home-vault-title">My Zettels</h2>
                        <span class="home-vault-count" id="zettel-count">0</span>
                    </div>
                    <div class="home-add-zettel" id="add-zettel-wrap">
                        <button class="home-add-btn" id="add-zettel-btn">
                            <span class="home-add-btn-text">+ Add Zettel</span>
                            <span class="home-add-btn-chevron">&#9662;</span>
                        </button>
                        <div class="home-add-dropdown" id="add-zettel-dropdown">
                            <form id="add-zettel-form" class="home-add-form">
                                <div class="home-add-row">
                                    <select id="add-source-type" class="home-add-select">
                                        <option value="">Auto-detect</option>
                                        <option value="youtube">YouTube</option>
                                        <option value="github">GitHub</option>
                                        <option value="reddit">Reddit</option>
                                        <option value="newsletter">Newsletter</option>
                                        <option value="generic">Web</option>
                                    </select>
                                    <input type="url" id="add-url-input" class="home-add-input" placeholder="https://..." required />
                                    <button type="submit" class="home-add-submit" id="add-submit-btn">Add</button>
                                </div>
                                <p class="home-add-error" id="add-error"></p>
                                <div class="home-add-loading hidden" id="add-loading">
                                    <div class="home-add-spinner"></div>
                                    <span>Processing...</span>
                                </div>
                            </form>
                        </div>
                    </div>
                </div>

                <!-- Card Grid -->
                <div class="home-card-grid" id="card-grid">
                    <!-- Cards injected by home.js -->
                </div>

                <!-- Empty State -->
                <div class="home-empty" id="empty-state">
                    <div class="home-empty-icon">&#x1F4D6;</div>
                    <h3 class="home-empty-title">No zettels yet</h3>
                    <p class="home-empty-text">Add your first zettel by pasting a URL above</p>
                </div>
            </section>

            <!-- Knowledge Graph Button -->
            <a href="/knowledge-graph" class="home-kg-btn">
                <div class="home-kg-btn-left">
                    <img src="/artifacts/logo-knowledge-graph.svg" alt="" width="28" height="28" class="home-kg-icon" />
                    <div class="home-kg-btn-text">
                        <span class="home-kg-btn-title">My Knowledge Graph</span>
                        <span class="home-kg-btn-sub">Explore connections between your zettels</span>
                    </div>
                </div>
                <span class="home-kg-btn-arrow">&rarr;</span>
            </a>
        </main>

        <!-- Avatar Picker Modal -->
        <div class="home-avatar-modal" id="avatar-modal">
            <div class="home-avatar-modal-overlay" id="avatar-modal-overlay"></div>
            <div class="home-avatar-modal-content">
                <button class="home-avatar-modal-close" id="avatar-modal-close">&times;</button>
                <h2 class="home-avatar-modal-title">Choose your avatar</h2>
                <div class="home-avatar-grid" id="avatar-grid">
                    <!-- 30 avatar options injected by home.js -->
                </div>
            </div>
        </div>

        <!-- Footer -->
        <footer class="footer">
            <a href="https://github.com/chintanmehta21/zettelkasten-telegram-bot" target="_blank" rel="noopener" class="footer-icon" title="View on GitHub">
                <svg width="20" height="20" viewBox="0 0 16 16" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"/></svg>
            </a>
        </footer>
    </div>

    <script src="/home/js/home.js"></script>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add website/features/home/index.html
git commit -m "feat: home page HTML structure"
```

---

### Task 6: Build Home Page CSS

**Files:**
- Create: `website/features/home/css/home.css`

- [ ] **Step 1: Write the complete home page CSS**

```css
/* ═══════════════════════════════════════════════════════════════════
   Home Page — Post-Login Dashboard
   Extends: style.css design tokens (loaded via <link>)
   ═══════════════════════════════════════════════════════════════════ */

/* ── Header overrides for home page ─────────────────────────────── */

.header {
    position: relative !important;
    display: block !important;
    text-align: center !important;
    width: 100% !important;
}

.header-auth {
    position: absolute !important;
    top: 3px !important;
    right: 0 !important;
    display: flex !important;
}

.branding {
    display: flex !important;
    flex-direction: column !important;
    align-items: center !important;
}

/* ── Avatar Button ──────────────────────────────────────────────── */

.home-avatar-wrap {
    position: relative;
}

.home-avatar-btn {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    border: 2px solid var(--border);
    background: var(--bg-tertiary);
    cursor: pointer;
    padding: 0;
    overflow: hidden;
    transition: border-color var(--transition), box-shadow var(--transition);
    display: flex;
    align-items: center;
    justify-content: center;
}

.home-avatar-btn:hover {
    border-color: var(--accent-muted);
    box-shadow: 0 0 0 3px var(--accent-glow);
}

.home-avatar-img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    border-radius: 50%;
}

.home-avatar-img.hidden {
    display: none;
}

.home-avatar-fallback {
    display: none;
    font-size: 0.85rem;
    font-weight: 600;
    color: var(--accent);
    text-transform: uppercase;
}

.home-avatar-fallback.visible {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    height: 100%;
}

/* ── Avatar Dropdown Menu ───────────────────────────────────────── */

.home-dropdown {
    display: none;
    position: absolute;
    top: calc(100% + 8px);
    right: 0;
    min-width: 200px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 0.375rem;
    z-index: 200;
    box-shadow: var(--shadow-lg);
}

.home-dropdown.open {
    display: block;
    animation: dropdownIn 0.15s ease;
}

@keyframes dropdownIn {
    from { opacity: 0; transform: translateY(-4px); }
    to { opacity: 1; transform: translateY(0); }
}

.home-dropdown-item {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    padding: 0.55rem 0.75rem;
    font-size: 0.82rem;
    color: var(--text-secondary);
    border-radius: var(--radius-sm);
    cursor: pointer;
    transition: all var(--transition);
    text-decoration: none;
    border: none;
    background: none;
    width: 100%;
    font-family: var(--font-body);
    text-align: left;
}

.home-dropdown-item:hover {
    background: var(--bg-elevated);
    color: var(--text-primary);
}

.home-dropdown-icon {
    font-size: 0.9rem;
    width: 20px;
    text-align: center;
    flex-shrink: 0;
}

.home-dropdown-divider {
    height: 1px;
    background: var(--border);
    margin: 0.25rem 0.5rem;
}

.home-dropdown-signout:hover {
    color: var(--error);
}

/* ── Welcome ────────────────────────────────────────────────────── */

.home-welcome {
    text-align: center;
    margin-bottom: 2rem;
    animation: fadeIn 0.5s ease;
}

.home-welcome-text {
    font-size: 1.6rem;
    font-weight: 600;
    color: var(--text-primary);
    letter-spacing: -0.02em;
}

@keyframes fadeIn {
    from { opacity: 0; transform: translateY(12px); }
    to { opacity: 1; transform: translateY(0); }
}

/* ── Vault Section ──────────────────────────────────────────────── */

.home-vault {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 48px 48px var(--radius-lg) var(--radius-lg);
    padding: 2rem;
    margin-bottom: 1.5rem;
    box-shadow: var(--shadow-md);
    animation: fadeIn 0.5s ease 0.1s both;
    position: relative;
    overflow: hidden;
}

.home-vault::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 80px;
    background: linear-gradient(to bottom, var(--accent-subtle), transparent);
    pointer-events: none;
    border-radius: 48px 48px 0 0;
}

.home-vault-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 1.5rem;
    position: relative;
    z-index: 1;
}

.home-vault-title-row {
    display: flex;
    align-items: center;
    gap: 0.6rem;
}

.home-vault-title {
    font-size: 1.2rem;
    font-weight: 600;
    color: var(--text-primary);
}

.home-vault-count {
    font-family: var(--font-mono);
    font-size: 0.7rem;
    font-weight: 500;
    padding: 0.15rem 0.5rem;
    background: var(--accent-glow);
    color: var(--accent);
    border-radius: 999px;
    border: 1px solid hsla(172, 66%, 50%, 0.2);
}

/* ── Add Zettel ─────────────────────────────────────────────────── */

.home-add-zettel {
    position: relative;
}

.home-add-btn {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.45rem 0.9rem;
    background: var(--accent);
    color: var(--text-inverted);
    border: none;
    border-radius: var(--radius-sm);
    font-family: var(--font-body);
    font-size: 0.82rem;
    font-weight: 600;
    cursor: pointer;
    transition: all var(--transition);
}

.home-add-btn:hover {
    background: var(--accent-hover);
    transform: translateY(-1px);
    box-shadow: 0 2px 8px hsla(172, 66%, 40%, 0.3);
}

.home-add-btn-chevron {
    font-size: 0.55rem;
    transition: transform var(--transition);
}

.home-add-btn.open .home-add-btn-chevron {
    transform: rotate(180deg);
}

.home-add-dropdown {
    display: none;
    position: absolute;
    top: calc(100% + 8px);
    right: 0;
    min-width: 400px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1rem;
    z-index: 100;
    box-shadow: var(--shadow-lg);
}

.home-add-dropdown.open {
    display: block;
    animation: dropdownIn 0.15s ease;
}

.home-add-row {
    display: flex;
    gap: 0.5rem;
    align-items: center;
}

.home-add-select {
    padding: 0.5rem 0.6rem;
    background: var(--bg-tertiary);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text-secondary);
    font-family: var(--font-mono);
    font-size: 0.78rem;
    cursor: pointer;
    min-width: 100px;
}

.home-add-select:focus {
    outline: none;
    border-color: var(--accent-muted);
}

.home-add-input {
    flex: 1;
    padding: 0.5rem 0.75rem;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text-primary);
    font-family: var(--font-mono);
    font-size: 0.82rem;
}

.home-add-input:focus {
    outline: none;
    border-color: var(--border-focus);
    box-shadow: 0 0 0 2px var(--accent-glow);
}

.home-add-input::placeholder {
    color: var(--text-muted);
}

.home-add-submit {
    padding: 0.5rem 1rem;
    background: var(--accent);
    color: var(--text-inverted);
    border: none;
    border-radius: var(--radius-sm);
    font-family: var(--font-body);
    font-size: 0.82rem;
    font-weight: 600;
    cursor: pointer;
    transition: background var(--transition);
    white-space: nowrap;
}

.home-add-submit:hover {
    background: var(--accent-hover);
}

.home-add-submit:disabled {
    opacity: 0.4;
    cursor: not-allowed;
}

.home-add-error {
    color: var(--error);
    font-size: 0.75rem;
    margin-top: 0.5rem;
    min-height: 0;
}

.home-add-loading {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-top: 0.5rem;
    color: var(--text-secondary);
    font-size: 0.8rem;
}

.home-add-spinner {
    width: 16px;
    height: 16px;
    border: 2px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
}

@keyframes spin {
    to { transform: rotate(360deg); }
}

/* ── Card Grid ──────────────────────────────────────────────────── */

.home-card-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
    gap: 1rem;
    position: relative;
    z-index: 1;
}

.home-card {
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1.25rem;
    cursor: pointer;
    transition: all var(--transition);
    text-decoration: none;
    color: inherit;
    display: block;
    animation: cardIn 0.3s ease both;
}

@keyframes cardIn {
    from { opacity: 0; transform: translateY(8px); }
    to { opacity: 1; transform: translateY(0); }
}

.home-card:hover {
    border-color: var(--border-light);
    transform: translateY(-2px);
    box-shadow: var(--shadow-md);
}

.home-card-source {
    font-family: var(--font-mono);
    font-size: 0.6rem;
    font-weight: 500;
    padding: 0.15rem 0.5rem;
    border-radius: 999px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    border: 1px solid;
    display: inline-block;
    margin-bottom: 0.6rem;
}

.home-card-source.youtube { color: hsl(355, 45%, 68%); border-color: hsla(355, 45%, 68%, 0.25); background: hsla(355, 45%, 68%, 0.08); }
.home-card-source.github { color: hsl(192, 35%, 62%); border-color: hsla(192, 35%, 62%, 0.25); background: hsla(192, 35%, 62%, 0.08); }
.home-card-source.reddit { color: hsl(28, 45%, 68%); border-color: hsla(28, 45%, 68%, 0.25); background: hsla(28, 45%, 68%, 0.08); }
.home-card-source.newsletter { color: hsl(205, 40%, 68%); border-color: hsla(205, 40%, 68%, 0.25); background: hsla(205, 40%, 68%, 0.08); }
.home-card-source.substack { color: hsl(205, 40%, 68%); border-color: hsla(205, 40%, 68%, 0.25); background: hsla(205, 40%, 68%, 0.08); }
.home-card-source.generic { color: hsl(220, 14%, 62%); border-color: hsla(220, 14%, 62%, 0.25); background: hsla(220, 14%, 62%, 0.08); }
.home-card-source.medium { color: hsl(142, 40%, 62%); border-color: hsla(142, 40%, 62%, 0.25); background: hsla(142, 40%, 62%, 0.08); }

.home-card-title {
    font-size: 0.9rem;
    font-weight: 600;
    color: var(--text-primary);
    margin-bottom: 0.4rem;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    line-height: 1.3;
}

.home-card-summary {
    font-size: 0.78rem;
    color: var(--text-secondary);
    margin-bottom: 0.6rem;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    line-height: 1.5;
}

.home-card-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem;
    margin-bottom: 0.5rem;
}

.home-card-tag {
    font-family: var(--font-mono);
    font-size: 0.6rem;
    padding: 0.1rem 0.4rem;
    border-radius: 999px;
    background: var(--bg-tertiary);
    color: var(--text-muted);
    border: 1px solid var(--border);
}

.home-card-date {
    font-family: var(--font-mono);
    font-size: 0.65rem;
    color: var(--text-muted);
}

/* ── Empty State ────────────────────────────────────────────────── */

.home-empty {
    text-align: center;
    padding: 3rem 1rem;
    position: relative;
    z-index: 1;
}

.home-empty.hidden {
    display: none;
}

.home-empty-icon {
    font-size: 2.5rem;
    margin-bottom: 1rem;
    opacity: 0.5;
}

.home-empty-title {
    font-size: 1.1rem;
    font-weight: 600;
    color: var(--text-primary);
    margin-bottom: 0.5rem;
}

.home-empty-text {
    font-size: 0.85rem;
    color: var(--text-muted);
}

/* ── Knowledge Graph Button ─────────────────────────────────────── */

.home-kg-btn {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 1.25rem 1.5rem;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    text-decoration: none;
    color: inherit;
    transition: all 0.25s ease;
    box-shadow: var(--shadow-sm);
    animation: fadeIn 0.5s ease 0.2s both;
}

.home-kg-btn:hover {
    border-color: hsla(172, 66%, 50%, 0.3);
    box-shadow: var(--shadow-md), 0 0 20px hsla(172, 66%, 50%, 0.08);
    transform: translateY(-1px);
}

.home-kg-btn-left {
    display: flex;
    align-items: center;
    gap: 1rem;
}

.home-kg-icon {
    flex-shrink: 0;
    filter: drop-shadow(0 0 4px hsla(172, 50%, 50%, 0.3));
}

.home-kg-btn-title {
    font-size: 1rem;
    font-weight: 600;
    color: var(--text-primary);
    display: block;
}

.home-kg-btn-sub {
    font-size: 0.78rem;
    color: var(--text-muted);
    display: block;
    margin-top: 0.15rem;
}

.home-kg-btn-arrow {
    font-size: 1.2rem;
    color: var(--accent);
    transition: transform var(--transition);
}

.home-kg-btn:hover .home-kg-btn-arrow {
    transform: translateX(4px);
}

/* ── Avatar Picker Modal ────────────────────────────────────────── */

.home-avatar-modal {
    display: none;
    position: fixed;
    inset: 0;
    z-index: 1000;
    align-items: center;
    justify-content: center;
}

.home-avatar-modal.open {
    display: flex;
}

.home-avatar-modal-overlay {
    position: absolute;
    inset: 0;
    background: hsla(0, 0%, 0%, 0.6);
    backdrop-filter: blur(4px);
}

.home-avatar-modal-content {
    position: relative;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 2rem;
    width: 100%;
    max-width: 480px;
    max-height: 80vh;
    overflow-y: auto;
    box-shadow: var(--shadow-lg);
    z-index: 1;
}

.home-avatar-modal-close {
    position: absolute;
    top: 0.75rem;
    right: 0.75rem;
    background: none;
    border: none;
    color: var(--text-muted);
    font-size: 1.2rem;
    cursor: pointer;
    padding: 0.25rem;
    line-height: 1;
    transition: color var(--transition);
}

.home-avatar-modal-close:hover {
    color: var(--text-primary);
}

.home-avatar-modal-title {
    font-size: 1.1rem;
    font-weight: 600;
    color: var(--text-primary);
    margin-bottom: 1.25rem;
}

.home-avatar-grid {
    display: grid;
    grid-template-columns: repeat(6, 1fr);
    gap: 0.75rem;
}

.home-avatar-option {
    width: 100%;
    aspect-ratio: 1;
    border-radius: 50%;
    border: 2px solid var(--border);
    cursor: pointer;
    overflow: hidden;
    transition: all var(--transition);
    padding: 0;
    background: var(--bg-tertiary);
}

.home-avatar-option:hover {
    border-color: var(--accent-muted);
    transform: scale(1.1);
}

.home-avatar-option.selected {
    border-color: var(--accent);
    box-shadow: 0 0 0 3px var(--accent-glow);
}

.home-avatar-option img {
    width: 100%;
    height: 100%;
    object-fit: cover;
}

/* ── Responsive ─────────────────────────────────────────────────── */

@media (max-width: 640px) {
    .home-vault {
        border-radius: var(--radius-lg);
        padding: 1.25rem;
    }

    .home-vault::before {
        border-radius: var(--radius-lg) var(--radius-lg) 0 0;
    }

    .home-vault-header {
        flex-direction: column;
        gap: 0.75rem;
    }

    .home-add-dropdown {
        min-width: unset;
        width: calc(100vw - 3rem);
        right: -1rem;
    }

    .home-add-row {
        flex-direction: column;
    }

    .home-add-select,
    .home-add-input,
    .home-add-submit {
        width: 100%;
    }

    .home-card-grid {
        grid-template-columns: 1fr;
    }

    .home-avatar-grid {
        grid-template-columns: repeat(5, 1fr);
    }

    .home-welcome-text {
        font-size: 1.25rem;
    }
}
```

- [ ] **Step 2: Commit**

```bash
git add website/features/home/css/home.css
git commit -m "feat: home page CSS with vault, cards, avatar, KG button"
```

---

### Task 7: Build Home Page JavaScript

**Files:**
- Create: `website/features/home/js/home.js`

- [ ] **Step 1: Write the complete home page JavaScript**

```javascript
/**
 * Home Page — Post-Login Dashboard
 *
 * Loads user profile, displays zettel vault, handles avatar menu,
 * and provides "Add Zettel" functionality.
 */

(function () {
  'use strict';

  var AVATAR_COUNT = 30;
  var _supabaseClient = null;
  var _currentSession = null;
  var _currentAvatarId = null;

  // ── DOM refs ──────────────────────────────────────────────────────

  var avatarBtn, avatarImg, avatarFallback, avatarDropdown, avatarWrap;
  var cardGrid, emptyState, zettelCount, userDisplayName;
  var addZettelBtn, addZettelDropdown, addZettelForm, addUrlInput;
  var addSourceType, addSubmitBtn, addError, addLoading;
  var avatarModal, avatarModalOverlay, avatarModalClose, avatarGrid;
  var menuProfile, menuSignout;

  function resolveDOM() {
    avatarBtn = document.getElementById('avatar-btn');
    avatarImg = document.getElementById('avatar-img');
    avatarFallback = document.getElementById('avatar-fallback');
    avatarDropdown = document.getElementById('avatar-dropdown');
    avatarWrap = document.getElementById('avatar-wrap');
    cardGrid = document.getElementById('card-grid');
    emptyState = document.getElementById('empty-state');
    zettelCount = document.getElementById('zettel-count');
    userDisplayName = document.getElementById('user-display-name');
    addZettelBtn = document.getElementById('add-zettel-btn');
    addZettelDropdown = document.getElementById('add-zettel-dropdown');
    addZettelForm = document.getElementById('add-zettel-form');
    addUrlInput = document.getElementById('add-url-input');
    addSourceType = document.getElementById('add-source-type');
    addSubmitBtn = document.getElementById('add-submit-btn');
    addError = document.getElementById('add-error');
    addLoading = document.getElementById('add-loading');
    avatarModal = document.getElementById('avatar-modal');
    avatarModalOverlay = document.getElementById('avatar-modal-overlay');
    avatarModalClose = document.getElementById('avatar-modal-close');
    avatarGrid = document.getElementById('avatar-grid');
    menuProfile = document.getElementById('menu-profile');
    menuSignout = document.getElementById('menu-signout');
  }

  // ── Init ──────────────────────────────────────────────────────────

  async function init() {
    resolveDOM();

    try {
      // Init Supabase client
      var resp = await fetch('/api/auth/config');
      var config = await resp.json();
      if (config.supabase_url && config.supabase_anon_key) {
        _supabaseClient = supabase.createClient(config.supabase_url, config.supabase_anon_key);
        var sessionResult = await _supabaseClient.auth.getSession();
        _currentSession = sessionResult.data.session;
      }
    } catch (e) {
      console.error('[home] Supabase init failed:', e);
    }

    // Auth guard — redirect if not logged in
    var token = _currentSession ? _currentSession.access_token : null;
    if (!token) {
      window.location.href = '/';
      return;
    }

    // Load user profile
    var profile = await fetchProfile(token);
    if (!profile) {
      window.location.href = '/';
      return;
    }

    // Set display name
    var displayName = profile.name || profile.email || 'User';
    if (userDisplayName) {
      userDisplayName.textContent = displayName.split(' ')[0];
    }

    // Set avatar
    await setupAvatar(profile, token);

    // Load zettels
    await loadZettels(token);

    // Bind events
    bindEvents(token);
  }

  // ── Profile ───────────────────────────────────────────────────────

  async function fetchProfile(token) {
    try {
      var resp = await fetch('/api/me', {
        headers: { 'Authorization': 'Bearer ' + token }
      });
      if (resp.status === 401) return null;
      return await resp.json();
    } catch (e) {
      console.error('[home] Profile fetch failed:', e);
      return null;
    }
  }

  // ── Avatar ────────────────────────────────────────────────────────

  async function setupAvatar(profile, token) {
    var avatarUrl = profile.avatar_url;

    // If no avatar set, assign a random one
    if (!avatarUrl || !avatarUrl.includes('/artifacts/avatars/')) {
      var randomId = Math.floor(Math.random() * AVATAR_COUNT);
      avatarUrl = '/artifacts/avatars/avatar_' + String(randomId).padStart(2, '0') + '.svg';
      _currentAvatarId = randomId;

      // Persist to server
      try {
        await fetch('/api/me/avatar', {
          method: 'PUT',
          headers: {
            'Authorization': 'Bearer ' + token,
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({ avatar_id: randomId })
        });
      } catch (e) {
        console.warn('[home] Avatar persist failed:', e);
      }
    } else {
      // Extract avatar_id from URL
      var match = avatarUrl.match(/avatar_(\d+)\.svg/);
      _currentAvatarId = match ? parseInt(match[1], 10) : 0;
    }

    // Display avatar
    if (avatarImg) {
      avatarImg.src = avatarUrl;
      avatarImg.onerror = function () {
        avatarImg.classList.add('hidden');
        if (avatarFallback) {
          var initial = (profile.name || profile.email || 'U')[0].toUpperCase();
          avatarFallback.textContent = initial;
          avatarFallback.classList.add('visible');
        }
      };
    }
  }

  async function updateAvatar(avatarId, token) {
    var avatarUrl = '/artifacts/avatars/avatar_' + String(avatarId).padStart(2, '0') + '.svg';
    _currentAvatarId = avatarId;

    // Update display
    if (avatarImg) {
      avatarImg.src = avatarUrl;
      avatarImg.classList.remove('hidden');
    }
    if (avatarFallback) {
      avatarFallback.classList.remove('visible');
    }

    // Persist
    try {
      await fetch('/api/me/avatar', {
        method: 'PUT',
        headers: {
          'Authorization': 'Bearer ' + token,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ avatar_id: avatarId })
      });
    } catch (e) {
      console.warn('[home] Avatar update failed:', e);
    }
  }

  // ── Zettels ───────────────────────────────────────────────────────

  async function loadZettels(token) {
    try {
      var resp = await fetch('/api/graph?view=my', {
        headers: { 'Authorization': 'Bearer ' + token }
      });
      var data = await resp.json();
      var nodes = data.nodes || [];

      // Sort by date descending
      nodes.sort(function (a, b) {
        return (b.date || '').localeCompare(a.date || '');
      });

      renderCards(nodes);
    } catch (e) {
      console.error('[home] Zettels load failed:', e);
      renderCards([]);
    }
  }

  function renderCards(nodes) {
    if (!cardGrid || !emptyState || !zettelCount) return;

    zettelCount.textContent = nodes.length;

    if (nodes.length === 0) {
      cardGrid.innerHTML = '';
      emptyState.classList.remove('hidden');
      return;
    }

    emptyState.classList.add('hidden');
    cardGrid.innerHTML = '';

    nodes.forEach(function (node, i) {
      var card = document.createElement('a');
      card.className = 'home-card';
      card.href = node.url || '#';
      card.target = '_blank';
      card.rel = 'noopener';
      card.style.animationDelay = (i * 0.04) + 's';

      var sourceClass = (node.group || 'generic').toLowerCase();
      var tags = (node.tags || []).slice(0, 3);
      var tagsHtml = tags.map(function (t) {
        return '<span class="home-card-tag">' + escapeHtml(t) + '</span>';
      }).join('');

      card.innerHTML =
        '<span class="home-card-source ' + sourceClass + '">' + escapeHtml(node.group || 'web') + '</span>' +
        '<h3 class="home-card-title">' + escapeHtml(node.name || 'Untitled') + '</h3>' +
        '<p class="home-card-summary">' + escapeHtml(node.summary || '') + '</p>' +
        (tagsHtml ? '<div class="home-card-tags">' + tagsHtml + '</div>' : '') +
        (node.date ? '<span class="home-card-date">' + escapeHtml(node.date) + '</span>' : '');

      cardGrid.appendChild(card);
    });
  }

  function escapeHtml(str) {
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  // ── Add Zettel ────────────────────────────────────────────────────

  async function addZettel(url, token) {
    if (addError) addError.textContent = '';
    if (addLoading) addLoading.classList.remove('hidden');
    if (addSubmitBtn) addSubmitBtn.disabled = true;

    try {
      var resp = await fetch('/api/summarize', {
        method: 'POST',
        headers: {
          'Authorization': 'Bearer ' + token,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ url: url })
      });

      if (!resp.ok) {
        var err = await resp.json();
        throw new Error(err.detail || 'Failed to process URL');
      }

      // Clear form
      if (addUrlInput) addUrlInput.value = '';
      if (addZettelDropdown) addZettelDropdown.classList.remove('open');
      if (addZettelBtn) addZettelBtn.classList.remove('open');

      // Reload zettels
      await loadZettels(token);
    } catch (e) {
      if (addError) addError.textContent = e.message;
    } finally {
      if (addLoading) addLoading.classList.add('hidden');
      if (addSubmitBtn) addSubmitBtn.disabled = false;
    }
  }

  // ── Avatar Picker Modal ──────────────────────────────────────────

  function openAvatarPicker(token) {
    if (!avatarModal || !avatarGrid) return;

    // Populate grid
    avatarGrid.innerHTML = '';
    for (var i = 0; i < AVATAR_COUNT; i++) {
      var btn = document.createElement('button');
      btn.className = 'home-avatar-option' + (i === _currentAvatarId ? ' selected' : '');
      btn.innerHTML = '<img src="/artifacts/avatars/avatar_' + String(i).padStart(2, '0') + '.svg" alt="Avatar ' + i + '" />';
      btn.setAttribute('data-avatar-id', i);

      btn.addEventListener('click', (function (id) {
        return function () {
          updateAvatar(id, token);
          // Update selection
          var all = avatarGrid.querySelectorAll('.home-avatar-option');
          all.forEach(function (el) { el.classList.remove('selected'); });
          this.classList.add('selected');
          // Close modal after short delay
          setTimeout(function () { closeAvatarPicker(); }, 300);
        };
      })(i));

      avatarGrid.appendChild(btn);
    }

    avatarModal.classList.add('open');
    document.body.style.overflow = 'hidden';
  }

  function closeAvatarPicker() {
    if (!avatarModal) return;
    avatarModal.classList.remove('open');
    document.body.style.overflow = '';
  }

  // ── Events ────────────────────────────────────────────────────────

  function bindEvents(token) {
    // Avatar dropdown toggle
    if (avatarBtn) {
      avatarBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        avatarDropdown.classList.toggle('open');
      });
    }

    // Close dropdown on outside click
    document.addEventListener('click', function (e) {
      if (avatarDropdown && !avatarWrap.contains(e.target)) {
        avatarDropdown.classList.remove('open');
      }
      if (addZettelDropdown && !document.getElementById('add-zettel-wrap').contains(e.target)) {
        addZettelDropdown.classList.remove('open');
        if (addZettelBtn) addZettelBtn.classList.remove('open');
      }
    });

    // Profile menu item → open avatar picker
    if (menuProfile) {
      menuProfile.addEventListener('click', function (e) {
        e.preventDefault();
        avatarDropdown.classList.remove('open');
        openAvatarPicker(token);
      });
    }

    // Sign out
    if (menuSignout) {
      menuSignout.addEventListener('click', async function () {
        if (_supabaseClient) {
          await _supabaseClient.auth.signOut();
        }
        window.location.href = '/';
      });
    }

    // Add Zettel toggle
    if (addZettelBtn) {
      addZettelBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        addZettelDropdown.classList.toggle('open');
        addZettelBtn.classList.toggle('open');
        if (addZettelDropdown.classList.contains('open') && addUrlInput) {
          addUrlInput.focus();
        }
      });
    }

    // Add Zettel form submit
    if (addZettelForm) {
      addZettelForm.addEventListener('submit', function (e) {
        e.preventDefault();
        var url = addUrlInput ? addUrlInput.value.trim() : '';
        if (url) addZettel(url, token);
      });
    }

    // Avatar modal close
    if (avatarModalClose) avatarModalClose.addEventListener('click', closeAvatarPicker);
    if (avatarModalOverlay) avatarModalOverlay.addEventListener('click', closeAvatarPicker);
  }

  // ── Start ─────────────────────────────────────────────────────────

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
```

- [ ] **Step 2: Commit**

```bash
git add website/features/home/js/home.js
git commit -m "feat: home page JS — auth, avatar, zettels, add-zettel"
```

---

### Task 8: Integration Testing and Polish

**Files:**
- Modify: `website/features/home/index.html` (if needed)
- Modify: `website/features/home/css/home.css` (if needed)
- Modify: `website/features/home/js/home.js` (if needed)

- [ ] **Step 1: Verify full app starts with no import errors**

Run: `python -c "from website.app import create_app; app = create_app(); print([r.path for r in app.routes if hasattr(r, 'path')])"`
Expected: Output includes `/home` in the route list

- [ ] **Step 2: Check all 30 avatar SVGs serve correctly**

Run: `python -c "import os; d='website/artifacts/avatars'; files=[f for f in os.listdir(d) if f.endswith('.svg')]; print(f'{len(files)} avatars found'); assert len(files)==30"`
Expected: `30 avatars found`

- [ ] **Step 3: Verify route file has no syntax errors**

Run: `python -c "from website.api.routes import router; print(f'{len(router.routes)} routes OK')"`
Expected: Route count printed, no errors

- [ ] **Step 4: Verify home page HTML loads CSS and JS correctly**

Check that `home/index.html` references:
- `/css/style.css` (shared design tokens)
- `/home/css/home.css` (home-specific styles)
- `/home/js/home.js` (home page logic)

Run: `grep -c 'style.css\|home.css\|home.js' website/features/home/index.html`
Expected: `3`

- [ ] **Step 5: Final commit**

```bash
git add -A website/features/home/ website/api/routes.py website/app.py website/core/supabase_kg/repository.py website/features/user_auth/
git commit -m "feat: complete post-login home page with vault, avatars, KG link"
```

---

## Task Dependency Graph

```
Task 1 (Avatars)          ─┐
Task 2 (API endpoint)     ─┤
Task 3 (FastAPI route)    ─┼─→ Task 5 (HTML) ─→ Task 6 (CSS) ─→ Task 7 (JS) ─→ Task 8 (Integration)
Task 4 (Auth redirect)    ─┘
```

Tasks 1–4 are independent and can run in parallel. Tasks 5–7 are sequential (HTML structure → CSS styling → JS logic). Task 8 is the integration verification.

## Files Created/Modified Summary

| File | Action | Purpose |
|------|--------|---------|
| `ops/scripts/generate_avatars.py` | Create | One-time DiceBear avatar download script |
| `website/artifacts/avatars/avatar_00-29.svg` | Create | 30 pre-generated SVG avatars |
| `website/api/routes.py` | Modify | Add `PUT /api/me/avatar` endpoint |
| `website/core/supabase_kg/repository.py` | Modify | Add `update_user_avatar()` method |
| `website/app.py` | Modify | Add `/home` route + static mounts |
| `website/features/user_auth/js/auth.js` | Modify | Redirect to `/home` after login |
| `website/features/user_auth/callback.html` | Modify | Default return path → `/home` |
| `website/features/home/index.html` | Create | Home page HTML structure |
| `website/features/home/css/home.css` | Create | Home page styles |
| `website/features/home/js/home.js` | Create | Home page logic |
