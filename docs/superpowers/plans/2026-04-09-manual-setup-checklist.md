# Render → DigitalOcean Migration — Manual Setup Walkthrough

> **ARCHIVED — Historical migration walkthrough (legacy, no longer used).** This document captured the one-time browser/SSH walkthrough for cutting over from Render.com to the DigitalOcean droplet. The migration is complete; Render is no longer used. The DigitalOcean droplet (Premium Intel 2 GB RAM / 1 vCPU / 70 GB NVMe SSD with Reserved IP, blue/green Docker Compose + Caddy) is the canonical and only production environment. **Do not execute any "pause Render" / "delete Render" / Render-dashboard step below** — they are preserved for context. See "Deployment Infrastructure (Canonical)" in the project root `CLAUDE.md` for the live setup.

> Companion to `2026-04-09-render-to-digitalocean-migration.md`. **All code is merged to master.** This document is a single linear walkthrough of every manual task (browser clicks, SSH sessions, dashboard configuration) needed to take the droplet from nothing to serving production traffic at `https://zettelkasten.in`.
>
> Work top to bottom. Do **not** skip steps. Do **not** touch the Render service until Task 32 — it is your rollback.

---

## Global ground rules

1. **Never paste a secret into a file in this repo.** All secrets go into your password manager (1Password / Bitwarden / Keeper / KeePassXC).
2. **Keep this document open in a browser tab while you work** — each task has exact screens, click paths, and verification commands.
3. **The Render service stays live** until Task 32. Your users won't notice anything until DNS flips in Task 25.
4. **Verification commands** live in fenced blocks after each task. If one fails, STOP and diagnose — do not move on.
5. **Git branch for hot fixes:** you will make at most one commit during this walkthrough (in Task 33, a README update). Everything else is dashboard work.

---

## Secrets Vault — fill in as you go

Paste each value into your password manager under an entry titled **Zettelkasten DO Migration**. Tick the box when collected.

### Existing (fetched from Render in Task 1)

| Secret | Collected? |
|---|---|
| `TELEGRAM_BOT_TOKEN` | - [ ] |
| `ALLOWED_CHAT_ID` | - [ ] |
| `GEMINI_API_KEYS` (10 keys, comma-joined) | - [ ] |
| `SUPABASE_URL` | - [ ] |
| `SUPABASE_ANON_KEY` | - [ ] |
| `GITHUB_TOKEN_FOR_NOTES` (the old `GITHUB_TOKEN` on Render) | - [ ] |
| `GITHUB_REPO_FOR_NOTES` (the old `GITHUB_REPO` on Render) | - [ ] |
| `NEXUS_GOOGLE_CLIENT_ID` | - [ ] |
| `NEXUS_GOOGLE_CLIENT_SECRET` | - [ ] |
| `NEXUS_GITHUB_CLIENT_ID` | - [ ] |
| `NEXUS_GITHUB_CLIENT_SECRET` | - [ ] |
| `NEXUS_REDDIT_CLIENT_ID` | - [ ] |
| `NEXUS_REDDIT_CLIENT_SECRET` | - [ ] |
| `NEXUS_TWITTER_CLIENT_ID` | - [ ] |
| `NEXUS_TWITTER_CLIENT_SECRET` | - [ ] |
| `NEXUS_TOKEN_ENCRYPTION_KEY` | - [ ] |

### New (generated during setup)

| Secret | Created in | Collected? |
|---|---|---|
| Cloudflare nameserver #1 | Task 4 | - [ ] |
| Cloudflare nameserver #2 | Task 4 | - [ ] |
| Cloudflare DS record (KeyTag, Algorithm, DigestType, Digest) | Task 7 | - [ ] |
| `DROPLET_IPV4` | Task 10 | - [ ] |
| `DROPLET_IPV6` | Task 10 | - [ ] |
| `DEPLOY_SSH_PRIVATE_KEY` (multi-line OpenSSH block) | Task 11 | - [ ] |
| `DEPLOY_SSH_PUBLIC_KEY` (single-line `ssh-ed25519 ...`) | Task 11 | - [ ] |
| `GHCR_READ_PAT` (`github_pat_...`) | Task 12 | - [ ] |
| `WEBHOOK_SECRET` (64-char hex) | Task 13 | - [ ] |

### Constants (for reference)

```
Domain:              zettelkasten.in
Admin email:         chintanoninternet@gmail.com
Repo:                chintanmehta21/Zettelkasten_KG  (PRIVATE)
DO region:           BLR1 (Bangalore)
Droplet size:        s-1vcpu-1gb  Premium AMD  $7/mo
Droplet hostname:    zettelkasten-prod
Deploy SSH user:     deploy
Deploy SSH port:     22
```

> **CRITICAL:** `SUPABASE_SERVICE_ROLE_KEY` must NEVER leave your Windows machine. Do not copy it to the vault, the droplet, or GitHub Actions.

---

# Task 1 — Fetch every existing env var value from Render

**Goal:** Collect every current production secret from Render into your password manager before you touch anything else. You'll paste these into GitHub Environment secrets in Task 15.

**Time:** 5 minutes.

### Detailed steps

- [ ] **1.1** Open https://dashboard.render.com/login in a browser and log in.
- [ ] **1.2** On the dashboard home, you should see a list of services. Click on your `zettelkasten` web service (the name you gave it when you first deployed).
- [ ] **1.3** On the service detail page, left sidebar → click **"Environment"** (between "Logs" and "Events").
- [ ] **1.4** You now see a table with columns **Key**, **Value** (hidden), and a **...** menu. For **each** row in the "Environment variables" section:
  1. Click the eye icon (👁) next to the value to reveal it.
  2. Click the copy icon (📋) to copy to clipboard.
  3. Paste into your password manager under the matching Secrets Vault row.

  Secrets to collect (these are the Render key names):
  ```
  TELEGRAM_BOT_TOKEN
  ALLOWED_CHAT_ID
  WEBHOOK_SECRET                  (if you already set one on Render — otherwise skip, we'll regenerate in Task 13)
  SUPABASE_URL
  SUPABASE_ANON_KEY
  GEMINI_API_KEY                  (if you still have a single-key value; otherwise it's in a Secret File — see step 1.5)
  GITHUB_TOKEN                    (paste into vault as GITHUB_TOKEN_FOR_NOTES)
  GITHUB_REPO                     (paste into vault as GITHUB_REPO_FOR_NOTES)
  NEXUS_GOOGLE_CLIENT_ID
  NEXUS_GOOGLE_CLIENT_SECRET
  NEXUS_GITHUB_CLIENT_ID
  NEXUS_GITHUB_CLIENT_SECRET
  NEXUS_REDDIT_CLIENT_ID
  NEXUS_REDDIT_CLIENT_SECRET
  NEXUS_TWITTER_CLIENT_ID
  NEXUS_TWITTER_CLIENT_SECRET
  NEXUS_TOKEN_ENCRYPTION_KEY
  ```
- [ ] **1.5** Still on the Environment page, scroll down to **"Secret Files"**. If there is a file named `api_env` (containing the 10 Gemini API keys, one per line), click it → click **View** → copy the entire content.
- [ ] **1.6** On your local machine, also check `C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\api_env` (if it exists). That file is the same list of 10 keys; use it as the authoritative source.
- [ ] **1.7** Convert the 10 keys (one per line) into a comma-joined string for the Secrets Vault `GEMINI_API_KEYS` entry. Example:
  ```
  key_one,key_two,key_three,key_four,key_five,key_six,key_seven,key_eight,key_nine,key_ten
  ```
  No spaces around commas. You can use an editor's find/replace (`\n` → `,`) to do this quickly.
- [ ] **1.8** Sanity-check: your password manager entry should now contain **all** the rows in the "Existing" table of the Secrets Vault.

### Verification

- [ ] You can read each value from your password manager without going back to Render.
- [ ] The Render service is still running (do NOT suspend it yet).

---

# Task 2 — Buy `zettelkasten.in` at GoDaddy

**Goal:** Secure the domain. We decline every upsell because Cloudflare gives us privacy, DNSSEC, and SSL for free.

**Time:** 5 minutes.
**Cost:** ~₹750/year (first-year promo) or ~₹1100/year (regular price).

### Detailed steps

- [ ] **2.1** Open https://www.godaddy.com in a browser. Log in to your existing GoDaddy account (or click **Sign In → Create Account** top right if you don't have one).
- [ ] **2.2** In the large search bar on the GoDaddy home page, type `zettelkasten.in` and press Enter.
- [ ] **2.3** On the results page, you should see "`zettelkasten.in` is available" with a green checkmark and a price. Click the blue **Add to Cart** button.
- [ ] **2.4** GoDaddy will throw **several** upsell screens. Decline every one:
  - **"Full Domain Privacy + Protection"** → click **No thanks** (small grey link at the bottom, not the blue button). Cloudflare's free WHOIS privacy replaces this.
  - **"Professional Email"** → **No thanks**
  - **"Websites + Marketing"** → **No thanks**
  - **"Web Hosting"** → **No thanks**
  - **"SSL Certificate"** → **No thanks** (Caddy will auto-provision free certs from Let's Encrypt)
  - **"Backup & Restore"** → **No thanks**
  - **"Website Security"** → **No thanks**
- [ ] **2.5** After all upsells, you land on the cart page. It should show:
  - `zettelkasten.in` — 1 year — ₹xxx
  - **Nothing else**
  - Total should be under ~₹1000
- [ ] **2.6** Click **Continue to Cart** → **Checkout**.
- [ ] **2.7** Choose your payment method (UPI / Card / Netbanking). Complete the purchase. You'll receive an order confirmation email.
- [ ] **2.8** Open https://account.godaddy.com/products to verify ownership. You should now see `zettelkasten.in` listed under **All Products → Domains**.

### Verification

```bash
# From any terminal — may take 1-2 minutes to appear in WHOIS
dig zettelkasten.in SOA +short
```

Expected: at least one line of output (showing GoDaddy's default `ns*.domaincontrol.com` nameservers). If empty, wait a minute and retry.

---

# Task 3 — Create a Cloudflare account

**Goal:** Get a free Cloudflare account so we can use their DNS (faster than GoDaddy, supports DNSSEC + CAA + analytics).

**Time:** 3 minutes.

### Detailed steps

- [ ] **3.1** Open https://dash.cloudflare.com/sign-up in a new tab.
- [ ] **3.2** Enter your email (`chintanoninternet@gmail.com`) and a **strong new password**. Store the password in your password manager.
- [ ] **3.3** Click **Create Account**.
- [ ] **3.4** Cloudflare sends a verification email → open your Gmail → click the verification link.
- [ ] **3.5** Back in Cloudflare, you land on the dashboard home. It will ask **"What do you want to do first?"** → choose **Connect a domain**. (If it skips this screen, that's fine — Task 4 starts from the same dashboard.)

### Verification

- [ ] You can log into https://dash.cloudflare.com and see an empty dashboard.

---

# Task 4 — Add `zettelkasten.in` to Cloudflare

**Goal:** Tell Cloudflare about the domain so it assigns you two nameservers you can point GoDaddy at.

**Time:** 3 minutes.

### Detailed steps

- [ ] **4.1** From the Cloudflare dashboard home, click the **+ Add a domain** button (top right).
- [ ] **4.2** On the "Connect a domain" screen, enter `zettelkasten.in` → click **Continue**.
- [ ] **4.3** **Select a plan** screen — scroll down to **Free $0/month** → click **Continue**.
- [ ] **4.4** **Review your DNS records** — Cloudflare scans for existing records. Since we just bought the domain, it will find nothing (or only a default A record). Click **Continue**.
- [ ] **4.5** **Change your nameservers** screen — Cloudflare displays two nameservers. They look like:
  ```
  amy.ns.cloudflare.com
  rick.ns.cloudflare.com
  ```
  (The exact names are randomly assigned; yours will differ.)
- [ ] **4.6** **COPY BOTH NAMESERVERS** into the Secrets Vault right now. You will paste these into GoDaddy in the next task.
- [ ] **4.7** Do **NOT** click "Done, check nameservers" yet — leave this Cloudflare tab open. We come back to it in Task 6.

### Verification

- [ ] Both nameservers are saved in your Secrets Vault entry.
- [ ] The Cloudflare tab still shows the "Change your nameservers" screen.

---

# Task 5 — Delegate DNS from GoDaddy to Cloudflare

**Goal:** Tell GoDaddy to stop serving DNS for `zettelkasten.in` and hand control to Cloudflare.

**Time:** 3 minutes to perform, then 15 min to 4 hours for propagation.

### Detailed steps

- [ ] **5.1** Open a new tab: https://account.godaddy.com/products
- [ ] **5.2** Under **Domains**, find `zettelkasten.in` and click the **DNS** link (or the three dots → **Manage DNS**).
- [ ] **5.3** On the DNS management page, scroll down to the **Nameservers** section (below the "Records" table).
- [ ] **5.4** Click the **Change** link in the Nameservers box.
- [ ] **5.5** A dialog appears with two options:
  - **"GoDaddy nameservers (default)"** (currently selected)
  - **"Enter my own nameservers (advanced)"**

  Select **"Enter my own nameservers (advanced)"**.
- [ ] **5.6** Two text fields appear (labeled **Nameserver 1** and **Nameserver 2**). Paste in the two Cloudflare nameservers from the Secrets Vault:
  ```
  Nameserver 1:  amy.ns.cloudflare.com    ← your actual NS
  Nameserver 2:  rick.ns.cloudflare.com   ← your actual NS
  ```
- [ ] **5.7** Click **Save**. GoDaddy will show a confirmation dialog **"Are you sure you want to update the nameservers?"** → click **Continue**.
- [ ] **5.8** GoDaddy displays a banner **"We are changing your nameservers"**. This means the change is recorded but not yet propagated.

### Verification

```bash
# Wait ~5 min then run from your local terminal
dig NS zettelkasten.in +short
```

Expected after propagation (anywhere from 15 min to 4 hours):
```
amy.ns.cloudflare.com.
rick.ns.cloudflare.com.
```

Retry every 10 minutes until only the Cloudflare nameservers appear. If you still see `*.domaincontrol.com` (GoDaddy), it hasn't propagated yet.

---

# Task 6 — Confirm Cloudflare sees the delegation

**Goal:** Cloudflare polls the parent zone to verify your nameservers are now live. Once confirmed, Cloudflare marks the zone **Active** and starts serving DNS.

**Time:** wait until Task 5 propagation finishes.

### Detailed steps

- [ ] **6.1** Return to the Cloudflare tab from Task 4 (the "Change your nameservers" screen). Click **Done, check nameservers**.
- [ ] **6.2** Cloudflare checks and shows either:
  - **"Great news! Cloudflare is now protecting your site."** → you're done with Task 6, zone is Active.
  - **"Your nameserver update is pending"** → click **Re-check now** every few minutes until it flips to active.
- [ ] **6.3** Cloudflare will also send a confirmation email **"zettelkasten.in is now active on Cloudflare"**.
- [ ] **6.4** Cloudflare may prompt you to enable some "Quick Start" features. Click through them selecting **Next** without toggling anything on (we'll configure manually).

### Verification

```bash
# Cloudflare should now be authoritative
dig SOA zettelkasten.in +short
```

Expected: starts with a `*.cloudflare.com` name, not `*.domaincontrol.com`.

---

# Task 7 — Enable DNSSEC on Cloudflare

**Goal:** Enable DNSSEC — Cloudflare signs DNS responses so attackers can't forge them. This needs one click on Cloudflare then a matching record on GoDaddy.

**Time:** 2 minutes on Cloudflare, 3 minutes on GoDaddy, 30 minutes for propagation.

### Detailed steps

- [ ] **7.1** In Cloudflare, make sure you're on the `zettelkasten.in` zone (top-left dropdown).
- [ ] **7.2** Left sidebar → **DNS → Settings** (not "Records", the **Settings** sub-page).
- [ ] **7.3** Scroll down to the **DNSSEC** card.
- [ ] **7.4** Click **Enable DNSSEC**.
- [ ] **7.5** Cloudflare shows a **DS Record** dialog with four labeled fields. **Copy all of them into the Secrets Vault** under "Cloudflare DS record":
  ```
  Key Tag:         <number like 2371>
  Algorithm:       13  (ECDSAP256SHA256)
  Digest Type:     2   (SHA256)
  Digest:          <long hex string>
  ```
  You can also click **Copy** next to the DS record summary to grab all four in one go.
- [ ] **7.6** Leave this dialog open. Do NOT close it until you've confirmed GoDaddy registered the record in Task 8.

### Verification

- [ ] The DS record values are in the Secrets Vault.

---

# Task 8 — Add the DS record to GoDaddy

**Goal:** GoDaddy forwards the DS record up the chain to the `.in` TLD registry, which publishes it. This completes the DNSSEC chain of trust.

**Time:** 3 minutes to perform, 15–30 minutes for propagation.

### Detailed steps

- [ ] **8.1** Go to https://account.godaddy.com/products → **Domains** → click **zettelkasten.in**.
- [ ] **8.2** On the domain management page, scroll down to the **Additional Settings** section.
- [ ] **8.3** Find **DNSSEC** → click **Manage**.
- [ ] **8.4** Click **Add DNSSEC**.
- [ ] **8.5** A form appears with four fields. Paste the four values from the Secrets Vault:
  ```
  Key Tag:       <Key Tag from Cloudflare>
  Algorithm:     ECDSAP256SHA256 (13)
  Digest Type:   SHA256 (2)
  Digest:        <Digest string from Cloudflare>
  ```
  GoDaddy's dropdown for Algorithm / Digest Type shows friendly names — match them to the numeric codes from Cloudflare:
  - Algorithm `13` → `ECDSAP256SHA256`
  - Digest Type `2` → `SHA256`
- [ ] **8.6** Click **Save**.
- [ ] **8.7** GoDaddy shows a banner **"DS record added"**. The `.in` registry publishes the DS within 30 minutes.

### Verification

Wait 20–30 minutes, then run:

```bash
dig zettelkasten.in +dnssec | grep -i 'flags:'
```

Look for `flags: qr rd ra ad` — the key indicator is **`ad`** (Authenticated Data). If not present, wait longer.

Alternative full check:
```bash
dig DS zettelkasten.in @1.1.1.1 +short
```
Expected: one line matching the Key Tag / Algorithm / Digest Type / Digest from Cloudflare.

---

# Task 9 — Add a CAA record restricting to Let's Encrypt

**Goal:** Only Let's Encrypt can issue SSL certs for `zettelkasten.in`. Prevents rogue issuance.

**Time:** 2 minutes.

### Detailed steps

- [ ] **9.1** Cloudflare → `zettelkasten.in` zone → **DNS → Records** (not Settings).
- [ ] **9.2** Click **+ Add record** (top right of the records table).
- [ ] **9.3** Fill in the form:
  - **Type:** select `CAA` from the dropdown
  - **Name:** `@` (Cloudflare automatically normalises to `zettelkasten.in`)
  - **Tag:** select `Only allow specific hostnames` from the dropdown (this maps to `issue`)
  - **CA domain name:** `letsencrypt.org`
  - **Flags:** `0` (default)
  - **TTL:** `Auto`
  - Leave "Proxy status" at default (CAA records cannot be proxied anyway)
- [ ] **9.4** Click **Save**.
- [ ] **9.5** The record appears in the DNS table. Leave everything else alone.

### Verification

```bash
dig zettelkasten.in CAA +short
```

Expected: `0 issue "letsencrypt.org"`

---

# Task 10 — Provision the DigitalOcean droplet

**Goal:** Spin up the $7/mo Premium AMD droplet in Bangalore with IPv6 enabled and your personal SSH key for bootstrap access.

**Time:** 5 minutes of form-filling + 60 seconds for droplet boot.
**Cost:** $7/mo (billed hourly from creation).

### Prerequisite

Your personal SSH public key must already exist on your Windows machine:

```bash
ls ~/.ssh/id_*.pub
```

If there is no output, create one now:
```bash
ssh-keygen -t ed25519 -C "chintan-personal-laptop" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub
```

Save the public key text for Task 10.7.

### Detailed steps

- [ ] **10.1** Open https://cloud.digitalocean.com. Sign in (or sign up if you don't have an account — DO offers $200 in free credit for the first 60 days for new signups).
- [ ] **10.2** In the top navbar, click the green **Create** dropdown → **Droplets**.
- [ ] **10.3** You land on the "Create Droplets" form. Work through each section top to bottom:

  **Section 1 — Choose Region**
  - Click the **Bangalore** card (BLR1 badge). It may be labelled "Bangalore, India".
  - Datacenter sub-pick: leave at default (e.g. `BLR1`).

  **Section 2 — Choose an image**
  - Click the **Marketplace** tab (NOT the "OS" tab).
  - In the search box, type `docker`.
  - Select **"Docker 5:28.x.x on Ubuntu 22.04"** (the exact version number changes over time — just pick the one for Ubuntu 22.04).

  **Section 3 — Choose Size**
  - **Droplet Type:** click **Basic**.
  - **CPU options:** click **Premium AMD** (NOT "Regular" or "Premium Intel").
  - **Machine options:** click the tile labelled `$7/mo` (`s-1vcpu-1gb-amd` — 1 vCPU / 1 GB RAM / 25 GB NVMe / 1 TB transfer).
  - **Fallback:** if the AMD tile shows "Sold out", click **Premium Intel** → select the `$7/mo` tile there instead.

  **Section 4 — Choose Authentication Method**
  - Select **SSH Key**.
  - Click **New SSH Key**.
  - In the popup:
    - **SSH key content:** paste the output of `cat ~/.ssh/id_ed25519.pub` (from the prerequisite above).
    - **Name:** `chintan-personal-laptop`
    - Click **Add SSH Key**.
  - Back on the main form, tick the checkbox next to `chintan-personal-laptop` to select this key for the droplet.

  **Section 5 — Recommended options**
  - **Enable improved metrics, monitoring, and alerting (free):** tick it.
  - **Enable automated backups:** **LEAVE UNCHECKED** (costs extra, and our data lives in Supabase + GHCR, per spec §13).
  - **Enable IPv6:** **TICK IT** (free, required by the spec).

  **Section 6 — Finalize and create**
  - **Quantity:** `1`
  - **Hostname:** change to `zettelkasten-prod`
  - **Tags:** type `zettelkasten` press Enter, then type `production` press Enter (two tags)
  - **Project:** leave at default
- [ ] **10.4** At the bottom, click the giant **Create Droplet** button. Wait ~60 seconds.
- [ ] **10.5** You'll be redirected to the droplet list page. The new droplet goes from "Creating…" to an IP address appearing.
- [ ] **10.6** Click on `zettelkasten-prod` to open the droplet detail page.
- [ ] **10.7** Copy the **ipv4** value (e.g. `159.89.xxx.xxx`) into Secrets Vault as `DROPLET_IPV4`.
- [ ] **10.8** Copy the **ipv6** value (a long `2400:6180:...` string) into Secrets Vault as `DROPLET_IPV6`.

### Verification

From your local Windows bash terminal:
```bash
# Replace <DROPLET_IPV4> with your actual IP
ssh -o StrictHostKeyChecking=accept-new root@<DROPLET_IPV4> 'uname -a && docker --version'
```

Expected output (example):
```
Linux zettelkasten-prod 5.15.0-102-generic #112-Ubuntu SMP ... x86_64 GNU/Linux
Docker version 28.1.1, build ...
```

If connection refused: wait another 30 seconds and retry (the droplet is still finishing boot).

After verification, type `exit` to leave the SSH session. Do not run any setup commands yet.

---

# Task 11 — Generate the `deploy` user SSH keypair

**Goal:** Create a dedicated keypair that GitHub Actions will use to SSH into the droplet as the `deploy` user. This is **different** from your personal key (Task 10) — the personal key is for root bootstrap, the deploy key is for CI deploys.

**Time:** 2 minutes.

### Detailed steps

- [ ] **11.1** Open a Git Bash / Windows bash terminal on your local machine.
- [ ] **11.2** Generate a fresh ed25519 keypair with no passphrase (GitHub Actions can't type a passphrase):
  ```bash
  ssh-keygen -t ed25519 -C "deploy@zettelkasten-prod" -f ~/.ssh/zettelkasten_deploy -N ""
  ```
  Expected output:
  ```
  Generating public/private ed25519 key pair.
  Your identification has been saved in /c/Users/LENOVO/.ssh/zettelkasten_deploy
  Your public key has been saved in /c/Users/LENOVO/.ssh/zettelkasten_deploy.pub
  The key fingerprint is:
  SHA256:xxxxxxxxxxx... deploy@zettelkasten-prod
  ```
- [ ] **11.3** Print the **public** key (single line):
  ```bash
  cat ~/.ssh/zettelkasten_deploy.pub
  ```
  The output looks like:
  ```
  ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAILongBase64String... deploy@zettelkasten-prod
  ```
  **Copy this single line** into Secrets Vault as `DEPLOY_SSH_PUBLIC_KEY`.
- [ ] **11.4** Print the **private** key (multi-line):
  ```bash
  cat ~/.ssh/zettelkasten_deploy
  ```
  The output looks like:
  ```
  -----BEGIN OPENSSH PRIVATE KEY-----
  b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gt
  ZWQyNTUxOQAAACB9MoreBase64Stuff...
  ...
  -----END OPENSSH PRIVATE KEY-----
  ```
  **Copy EVERYTHING** including the BEGIN/END lines and the final trailing newline. Paste into Secrets Vault as `DEPLOY_SSH_PRIVATE_KEY`.
- [ ] **11.5** (Optional but recommended) Back up both files to your password manager as encrypted attachments, separate from the raw text entries.

### Verification

```bash
# Both files should exist with strict permissions
ls -l ~/.ssh/zettelkasten_deploy*
```

Expected: two files, private key should be `-rw-------` (0600) — or at least `-rw-r--r--` on Windows Git Bash which has weaker permissions.

**Security warning:** never commit these files to git. They live in `~/.ssh/`, which is outside the repo, so as long as you don't copy them into `C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\`, you are safe.

---

# Task 12 — Generate the fine-grained `GHCR_READ_PAT`

**Goal:** Create a GitHub Personal Access Token (fine-grained) that allows only one thing: reading the private container image from GHCR. The droplet will use this token to `docker login` and `docker pull` at deploy time.

**Time:** 5 minutes.
**Expiration:** 365 days. Set a calendar reminder to rotate at ~330 days.

### Why "fine-grained" and not "classic"

- **Classic PAT:** scopes apply to every repo you have access to. One leaked token = all your repos compromised.
- **Fine-grained PAT:** scoped to a single repository (`Zettelkasten_KG`) and a single permission (`Packages: Read`). One leaked token = only GHCR pulls for that one repo.

### Detailed steps

- [ ] **12.1** Open https://github.com/login and sign in as `chintanmehta21`.
- [ ] **12.2** Top-right → click your profile avatar → **Settings**.
- [ ] **12.3** Left sidebar (bottom) → **Developer settings**.
- [ ] **12.4** Left sidebar → **Personal access tokens → Fine-grained tokens**.
- [ ] **12.5** Click the green **Generate new token** button (top right).
- [ ] **12.6** You land on the fine-grained token creation form. Fill it in **exactly**:

  **Token name**
  ```
  zettelkasten-droplet-ghcr-read
  ```

  **Description** (optional but helpful)
  ```
  Read-only GHCR pull access for the Zettelkasten DO droplet. Rotate annually.
  ```

  **Resource owner**
  - Dropdown: select `chintanmehta21` (your personal account, NOT an organization).

  **Expiration**
  - Dropdown: select **Custom...**
  - Date picker: pick exactly **365 days from today**. GitHub shows the exact date under the picker.

  **Repository access**
  - Radio: **Only select repositories**
  - Dropdown that appears: click it, search for `Zettelkasten_KG`, tick the checkbox next to it. Only this repo should be selected.

  **Permissions**
  - Scroll to the **Repository permissions** section. Leave EVERYTHING at default (no access). Do not grant any repository-level permission.
  - Scroll to **Account permissions** (further down).
  - Find the row labelled **Packages**. Click the dropdown → change from `No access` → **Read-only**.
  - Leave all other Account permissions at "No access".
- [ ] **12.7** Scroll to the very bottom → click the green **Generate token** button.
- [ ] **12.8** GitHub shows a confirmation screen with your new token — a string starting with `github_pat_11...`.
- [ ] **12.9** **COPY THE TOKEN IMMEDIATELY.** GitHub will never show it again. Paste into Secrets Vault as `GHCR_READ_PAT`.
- [ ] **12.10** **Do not navigate away** from the screen until the token is saved in your password manager. If you lose it, you have to generate a new one.

### Verification

Test the token works from your local machine:
```bash
# Paste the token when prompted, or export it first
echo "<paste_token_here>" | docker login ghcr.io -u chintanmehta21 --password-stdin
```

Expected: `Login Succeeded`. Then log out:
```bash
docker logout ghcr.io
```

(Note: the first pull will happen later from the droplet during the deploy, not from your laptop.)

### Set a calendar reminder

- [ ] Add a Google Calendar event for **340 days from now** titled **"Rotate GHCR_READ_PAT for zettelkasten droplet"** with a 1-week advance notification. The actual token expires in 365 days, so 340 days gives you a buffer.

---

# Task 13 — Generate a fresh `WEBHOOK_SECRET`

**Goal:** A random 64-character hex string that Telegram will send in the `X-Telegram-Bot-Api-Secret-Token` header on every webhook call. The droplet verifies this header matches before accepting the request.

**Time:** 30 seconds.

### Detailed steps

- [ ] **13.1** In a Git Bash / WSL / Linux terminal:
  ```bash
  openssl rand -hex 32
  ```
  Expected output (yours will differ):
  ```
  a3f2c8d14b5e6f7890abcd1234ef5678901234567890abcdef1234567890abcd
  ```
- [ ] **13.2** Copy the hex string into Secrets Vault as `WEBHOOK_SECRET`.
- [ ] **13.3** **Do NOT call Telegram `setWebhook` yet.** Render is still handling the bot with the old secret. We'll switch both in one atomic step in Task 28.

> **Alternative:** if you already saved the existing `WEBHOOK_SECRET` from Render in Task 1, you can reuse that value here instead. Either is fine — rotating is slightly more hygienic.

---

# Task 14 — Create the GitHub `production` Environment

**Goal:** GitHub Environments are a layer above repo secrets that let you add approval gates. The `deploy-droplet.yml` workflow references `environment: production`, which means every deploy waits for your manual approval.

**Time:** 3 minutes.

### Detailed steps

- [ ] **14.1** Open https://github.com/chintanmehta21/Zettelkasten_KG/settings/environments
- [ ] **14.2** Click the green **New environment** button.
- [ ] **14.3** **Name:** `production` (lowercase, exactly this string — the workflow references it by name).
- [ ] **14.4** Click **Configure environment**.
- [ ] **14.5** You land on the environment configuration page. Three sections to configure:

  **Deployment protection rules**
  - Tick **Required reviewers**.
  - A search box appears → type `chintanmehta21` → select yourself.
  - Leave the "Prevent self-review" checkbox **unticked** (you are the only reviewer, you have to approve your own deploys).
  - Tick **Wait timer** → leave at `0` minutes (no forced wait; you approve when ready).
  - Tick **Allow administrators to bypass configured protection rules** only if you want emergency override — otherwise leave it unchecked for stricter safety.

  **Deployment branches and tags**
  - Dropdown: change from "No restriction" to **Selected branches and tags**.
  - Click **Add deployment branch or tag rule**.
  - Type: **Branch**
  - Name pattern: `master`
  - Click **Add rule**.
  - Now only `master` branch can trigger deploys targeting the `production` environment.

  **Environment secrets**
  - Leave this section empty for now. We add secrets in Task 15.
- [ ] **14.6** Click **Save protection rules** (bottom of the page).

### Verification

- [ ] You see a green banner **"production environment configured successfully"**.
- [ ] Going back to `https://github.com/chintanmehta21/Zettelkasten_KG/settings/environments` shows `production` in the list with a lock icon (indicating protection rules are active).

---

# Task 15 — Add all Environment secrets

**Goal:** Paste every value from the Secrets Vault into the GitHub `production` environment, using the exact secret names the workflow expects.

**Time:** 15 minutes (24 secrets to add).

### Secret name reference

These names **must match exactly** — they come directly from `.github/workflows/deploy-droplet.yml`:

```
DROPLET_HOST
DROPLET_SSH_USER
DROPLET_SSH_KEY
DROPLET_SSH_PORT
GHCR_READ_PAT
TELEGRAM_BOT_TOKEN
ALLOWED_CHAT_ID
WEBHOOK_SECRET
GEMINI_API_KEYS
SUPABASE_URL
SUPABASE_ANON_KEY
GITHUB_TOKEN_FOR_NOTES
GITHUB_REPO_FOR_NOTES
NEXUS_GOOGLE_CLIENT_ID
NEXUS_GOOGLE_CLIENT_SECRET
NEXUS_GITHUB_CLIENT_ID
NEXUS_GITHUB_CLIENT_SECRET
NEXUS_REDDIT_CLIENT_ID
NEXUS_REDDIT_CLIENT_SECRET
NEXUS_TWITTER_CLIENT_ID
NEXUS_TWITTER_CLIENT_SECRET
NEXUS_TOKEN_ENCRYPTION_KEY
```

Total: **22 secrets**.

### Detailed steps

- [ ] **15.1** Go to https://github.com/chintanmehta21/Zettelkasten_KG/settings/environments/production (or click on `production` in the environments list).
- [ ] **15.2** Scroll down to **Environment secrets**.
- [ ] **15.3** For each secret in the list above, do the following:
  1. Click **Add environment secret**.
  2. **Name:** paste the exact secret name from the list.
  3. **Value:** paste the value from your Secrets Vault.
  4. Click **Add secret**.
  5. The secret appears in the list with a hidden value and an **Update** button.

  Go through them in this order — it matches the natural grouping:

  **Infra secrets (5):**
  ```
  DROPLET_HOST          → <DROPLET_IPV4> from Secrets Vault (just the IP, no http://)
  DROPLET_SSH_USER      → deploy              (literal string, no quotes)
  DROPLET_SSH_KEY       → <DEPLOY_SSH_PRIVATE_KEY> — paste the full multi-line block
                          INCLUDING -----BEGIN/END OPENSSH PRIVATE KEY----- lines
                          AND the trailing newline
  DROPLET_SSH_PORT      → 22                  (literal string, no quotes)
  GHCR_READ_PAT         → <github_pat_...> from Secrets Vault
  ```

  **App runtime secrets (8):**
  ```
  TELEGRAM_BOT_TOKEN    → <from Render>
  ALLOWED_CHAT_ID       → <from Render>
  WEBHOOK_SECRET        → <from Task 13>
  GEMINI_API_KEYS       → <10 keys joined with commas, no spaces>
  SUPABASE_URL          → <from Render, e.g. https://xxx.supabase.co>
  SUPABASE_ANON_KEY     → <from Render, long eyJ... JWT>
  GITHUB_TOKEN_FOR_NOTES → <the old GITHUB_TOKEN from Render>
  GITHUB_REPO_FOR_NOTES  → <the old GITHUB_REPO from Render, e.g. chintanmehta21/obsidian-kg>
  ```

  **Nexus OAuth secrets (9):**
  ```
  NEXUS_GOOGLE_CLIENT_ID
  NEXUS_GOOGLE_CLIENT_SECRET
  NEXUS_GITHUB_CLIENT_ID
  NEXUS_GITHUB_CLIENT_SECRET
  NEXUS_REDDIT_CLIENT_ID
  NEXUS_REDDIT_CLIENT_SECRET
  NEXUS_TWITTER_CLIENT_ID
  NEXUS_TWITTER_CLIENT_SECRET
  NEXUS_TOKEN_ENCRYPTION_KEY
  ```

- [ ] **15.4** After adding all 22 secrets, scroll through the list and **count**. You should see exactly 22 rows.
- [ ] **15.5** **CRITICAL VERIFY:** scan the list. `SUPABASE_SERVICE_ROLE_KEY` must NOT appear. If you see it by accident, click its **Remove** button immediately.
- [ ] **15.6** Cross-check against the workflow file: https://github.com/chintanmehta21/Zettelkasten_KG/blob/master/.github/workflows/deploy-droplet.yml — search for `secrets.` and verify every reference exists in your environment.

### Verification

- [ ] 22 secrets listed under environment `production`
- [ ] `SUPABASE_SERVICE_ROLE_KEY` is **not** in the list
- [ ] Every secret name matches the exact spelling in `.github/workflows/deploy-droplet.yml`

---

# Task 16 — Copy the `ops/` tree up to the droplet

**Goal:** The bootstrap script needs several config files already on disk. We SCP them up before running bootstrap.

**Time:** 2 minutes.

### Detailed steps

- [ ] **16.1** Make sure you are on the latest master locally:
  ```bash
  cd "C:/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault"
  git checkout master
  git pull origin master
  git log --oneline -3
  ```
  Verify the most recent commits are from the migration branch (you should see `feat(host):` / `feat(deploy):` / `feat(compose):` commits near the top).
- [ ] **16.2** SSH to the droplet as root using your personal key (same one you uploaded in Task 10):
  ```bash
  ssh root@<DROPLET_IPV4>
  ```
  First connection: answer `yes` to the host key prompt.
- [ ] **16.3** On the droplet, create the cache directory and exit:
  ```bash
  mkdir -p /opt/zettelkasten/repo-cache/ops
  exit
  ```
- [ ] **16.4** From your local machine, copy the ops tree to the droplet:
  ```bash
  cd "C:/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault"
  scp -r ops/host ops/systemd ops/caddy ops/deploy \
        ops/docker-compose.blue.yml \
        ops/docker-compose.green.yml \
        ops/docker-compose.caddy.yml \
        root@<DROPLET_IPV4>:/opt/zettelkasten/repo-cache/ops/
  ```
  Expected: a list of files being uploaded, no errors. Total transfer is under 100 KB.
- [ ] **16.5** SSH back in and verify the tree:
  ```bash
  ssh root@<DROPLET_IPV4>
  ls -R /opt/zettelkasten/repo-cache/ops/
  ```
  Expected directories: `host/`, `systemd/`, `caddy/`, `deploy/`, and the three `docker-compose.*.yml` files at the top level of `ops/`.

### Verification

```bash
# Still on the droplet as root
ls /opt/zettelkasten/repo-cache/ops/host/bootstrap.sh
ls /opt/zettelkasten/repo-cache/ops/host/sysctl-zettelkasten.conf
ls /opt/zettelkasten/repo-cache/ops/host/logrotate-zettelkasten.conf
ls /opt/zettelkasten/repo-cache/ops/systemd/zettelkasten.service
ls /opt/zettelkasten/repo-cache/ops/caddy/Caddyfile
ls /opt/zettelkasten/repo-cache/ops/caddy/upstream.snippet
```
All six commands should succeed with no `No such file` errors.

---

# Task 17 — Run `bootstrap.sh` on the droplet

**Goal:** Run the idempotent bootstrap script. It installs UFW, fail2ban, unattended-upgrades, configures sysctl + swap + file descriptor limits, creates the `deploy` user with your SSH public key, creates the Docker network, creates all the `/opt/zettelkasten/` directories, and disables root SSH.

**Time:** ~2 minutes of script execution.

### Detailed steps

- [ ] **17.1** If you got disconnected, SSH back in as root:
  ```bash
  ssh root@<DROPLET_IPV4>
  ```
- [ ] **17.2** Export the deploy public key as an environment variable. The bootstrap script reads `DEPLOY_PUBKEY` to create the `deploy` user's `~/.ssh/authorized_keys`.

  Paste the one-line public key from Secrets Vault (starts with `ssh-ed25519 AAAA...`):
  ```bash
  export DEPLOY_PUBKEY='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI...your actual key... deploy@zettelkasten-prod'
  ```
  **Use single quotes** so the shell doesn't try to expand anything in the key text.
- [ ] **17.3** Sanity-check the variable is set:
  ```bash
  echo "${#DEPLOY_PUBKEY}"
  ```
  Expected: a number around `80-100` (length of the key string). If `0`, the variable didn't stick — re-run the export.
- [ ] **17.4** Run the bootstrap script:
  ```bash
  bash /opt/zettelkasten/repo-cache/ops/host/bootstrap.sh
  ```
- [ ] **17.5** Watch the output. You'll see several `[bootstrap] ...` log lines:
  - Installing apt packages (ufw, fail2ban, unattended-upgrades, logrotate, jq, curl)
  - Configuring unattended-upgrades
  - Configuring UFW rules
  - Enabling fail2ban
  - Creating 1 GB swapfile
  - Installing sysctl tuning
  - Configuring file descriptor limits
  - Creating `deploy` user
  - Creating Docker network `zettelnet`
  - Creating `/opt/zettelkasten/` directory tree
  - Installing logrotate config
  - Installing + enabling systemd unit
  - Disabling root SSH login
  - Final line: `[bootstrap] DONE.`
- [ ] **17.6** If the script errors out, read the output carefully. Common issues:
  - `DEPLOY_PUBKEY env var is required` → step 17.2 failed
  - `Must run as root` → you're running as a non-root user, SSH back in as root
  - Apt lock held → a background unattended-upgrade is running; wait 2 minutes and retry

### Verification

```bash
# Still on the droplet as root
ufw status verbose
```
Expected:
```
Status: active
...
22/tcp    ALLOW IN  Anywhere     # SSH
80/tcp    ALLOW IN  Anywhere     # HTTP
443/tcp   ALLOW IN  Anywhere     # HTTPS
443/udp   ALLOW IN  Anywhere     # HTTP/3 QUIC
...
```

```bash
swapon --show
```
Expected: `/swapfile file 1024M 0B -2` (or similar — the key is `1024M`).

```bash
id deploy
```
Expected: `uid=1001(deploy) gid=1001(deploy) groups=1001(deploy),999(docker)` — note the `docker` group membership.

```bash
docker network ls | grep zettelnet
```
Expected: one line showing `zettelnet` with driver `bridge`.

```bash
ls /opt/zettelkasten/
```
Expected: `ACTIVE_COLOR`, `caddy/`, `compose/`, `data/`, `deploy/`, `logs/`, `repo-cache/`

```bash
cat /opt/zettelkasten/ACTIVE_COLOR
```
Expected: `blue` (initial value — meaning "blue is the active slot, green is idle ready for first deploy").

---

# Task 18 — Install static configs into their permanent locations

**Goal:** The bootstrap script creates the directory tree but doesn't populate it with the Caddyfile, compose files, and deploy scripts. Do that now.

**Time:** 1 minute.

### Detailed steps

- [ ] **18.1** Still on the droplet as root, install each file to its permanent location with the right mode:
  ```bash
  install -m 0644 /opt/zettelkasten/repo-cache/ops/caddy/Caddyfile         /opt/zettelkasten/caddy/Caddyfile
  install -m 0644 /opt/zettelkasten/repo-cache/ops/caddy/upstream.snippet  /opt/zettelkasten/caddy/upstream.snippet
  install -m 0644 /opt/zettelkasten/repo-cache/ops/docker-compose.blue.yml  /opt/zettelkasten/compose/docker-compose.blue.yml
  install -m 0644 /opt/zettelkasten/repo-cache/ops/docker-compose.green.yml /opt/zettelkasten/compose/docker-compose.green.yml
  install -m 0644 /opt/zettelkasten/repo-cache/ops/docker-compose.caddy.yml /opt/zettelkasten/compose/docker-compose.caddy.yml
  install -m 0755 /opt/zettelkasten/repo-cache/ops/deploy/deploy.sh         /opt/zettelkasten/deploy/deploy.sh
  install -m 0755 /opt/zettelkasten/repo-cache/ops/deploy/rollback.sh       /opt/zettelkasten/deploy/rollback.sh
  install -m 0755 /opt/zettelkasten/repo-cache/ops/deploy/healthcheck.sh    /opt/zettelkasten/deploy/healthcheck.sh
  ```
- [ ] **18.2** Change ownership to the `deploy` user so GitHub Actions can edit them over SSH:
  ```bash
  chown -R deploy:deploy /opt/zettelkasten/caddy /opt/zettelkasten/compose /opt/zettelkasten/deploy
  ```

### Verification

```bash
ls -l /opt/zettelkasten/caddy/ /opt/zettelkasten/compose/ /opt/zettelkasten/deploy/
```
Expected: all files owned by `deploy:deploy`, compose files at 0644, deploy scripts at 0755.

---

# Task 19 — Verify the `deploy` user can SSH in

**Goal:** Confirm the `deploy` user's `authorized_keys` works and that GitHub Actions will be able to connect.

**Time:** 1 minute.

### Detailed steps

- [ ] **19.1** On the droplet, log out:
  ```bash
  exit
  ```
- [ ] **19.2** From your local Windows bash, connect as `deploy` using the deploy key from Task 11:
  ```bash
  ssh -i ~/.ssh/zettelkasten_deploy deploy@<DROPLET_IPV4> 'whoami && docker ps && ls /opt/zettelkasten/'
  ```
  Expected output:
  ```
  deploy
  CONTAINER ID   IMAGE  ...  (empty table — no containers running yet)
  ACTIVE_COLOR  caddy  compose  data  deploy  logs  repo-cache
  ```

If you get `Permission denied (publickey)`, the `authorized_keys` file on the droplet doesn't have your deploy public key. SSH back in as root and check:
```bash
ssh root@<DROPLET_IPV4> 'cat /home/deploy/.ssh/authorized_keys'
```
It should match `DEPLOY_SSH_PUBLIC_KEY` in your Secrets Vault. If not, fix it manually:
```bash
ssh root@<DROPLET_IPV4>
echo 'ssh-ed25519 AAAA...your public key...' >> /home/deploy/.ssh/authorized_keys
chown deploy:deploy /home/deploy/.ssh/authorized_keys
chmod 600 /home/deploy/.ssh/authorized_keys
```

### Verification

- [ ] `ssh -i ~/.ssh/zettelkasten_deploy deploy@<DROPLET_IPV4> 'echo OK'` prints `OK`.

---

# Task 20 — Confirm root SSH is disabled

**Goal:** Bootstrap disables root login at the end. Double-check attackers can't SSH as root.

**Time:** 1 minute.

### Detailed steps

- [ ] **20.1** From your local machine, attempt to SSH as root. **This should FAIL**:
  ```bash
  ssh root@<DROPLET_IPV4>
  ```
  Expected: `Permission denied (publickey).` — meaning `PermitRootLogin no` is in effect.
- [ ] **20.2** Confirm deploy user SSH still works (regression check):
  ```bash
  ssh -i ~/.ssh/zettelkasten_deploy deploy@<DROPLET_IPV4> 'echo OK'
  ```
  Expected: `OK`

If you ever need emergency root access, use the DigitalOcean **Droplet Console** in the dashboard (Recovery → Console Access). That bypasses SSH.

### Verification

- [ ] Root SSH denied.
- [ ] Deploy SSH works.

---

# Task 21 — Add staging DNS records (`stage.zettelkasten.in`)

**Goal:** Point a staging subdomain at the droplet so the first deploy provisions a Let's Encrypt cert for `stage` without touching the apex (which is still on Render).

**Time:** 2 minutes to perform, 1–2 minutes for Cloudflare to serve.

### Detailed steps

- [ ] **21.1** Cloudflare → `zettelkasten.in` zone → **DNS → Records**.
- [ ] **21.2** Click **+ Add record**.
- [ ] **21.3** Fill in the A record:
  - **Type:** `A`
  - **Name:** `stage` (Cloudflare will display it as `stage.zettelkasten.in`)
  - **IPv4 address:** `<DROPLET_IPV4>` from Secrets Vault
  - **Proxy status:** click the cloud icon to toggle it to **grey** (DNS only). **Do NOT leave it orange** — Caddy needs to see real client IPs for Let's Encrypt HTTP-01 challenges.
  - **TTL:** `Auto`
- [ ] **21.4** Click **Save**.
- [ ] **21.5** Click **+ Add record** again.
- [ ] **21.6** Fill in the AAAA record:
  - **Type:** `AAAA`
  - **Name:** `stage`
  - **IPv6 address:** `<DROPLET_IPV6>` from Secrets Vault
  - **Proxy status:** grey cloud (DNS only)
  - **TTL:** `Auto`
- [ ] **21.7** Click **Save**.

### Verification

```bash
dig stage.zettelkasten.in A    +short
dig stage.zettelkasten.in AAAA +short
```
Expected: the droplet's IPv4 and IPv6 respectively. May take 1–2 minutes to appear.

---

# Task 22 — Trigger the first deploy to staging

**Goal:** Run the `deploy-droplet.yml` workflow against `stage.zettelkasten.in`. This builds the image, pushes it to private GHCR, SSHes into the droplet, pulls the image, starts the idle color, health-checks it, flips Caddy, and drains the old color.

**Time:** ~8 minutes (2 min test, 3 min build+push, 1 min wait for approval, 2 min deploy).

### Detailed steps

- [ ] **22.1** Open https://github.com/chintanmehta21/Zettelkasten_KG/actions/workflows/deploy-droplet.yml
- [ ] **22.2** Top right → click **Run workflow** (dropdown button).
- [ ] **22.3** A form drops down:
  - **Use workflow from:** `Branch: master`
  - **Caddy hostname to deploy:** `stage.zettelkasten.in` (overwrite the default `zettelkasten.in`)
- [ ] **22.4** Click the green **Run workflow** button inside the dropdown.
- [ ] **22.5** A new run appears in the list within a few seconds. Click on it.
- [ ] **22.6** The run page shows the pipeline with three jobs:
  - **pytest (mocked)** — runs the unit test suite with stubbed creds (~2 min)
  - **Build & push image** — docker buildx → push to `ghcr.io/chintanmehta21/zettelkasten-kg-website:<sha>` (~3 min)
  - **Deploy** — needs approval
- [ ] **22.7** Wait for `pytest` and `Build & push image` to finish green.
- [ ] **22.8** The `Deploy` job shows **"Waiting for review"** with an orange clock icon.
- [ ] **22.9** Click the yellow banner **"Review pending deployments"** at the top of the run page.
- [ ] **22.10** A modal appears:
  - Checkbox: **production** — tick it
  - Comment (optional): `first staging deploy`
  - Click **Approve and deploy**.
- [ ] **22.11** The Deploy job starts. Click it to watch logs. You should see:
  - SSH connection established to the droplet as `deploy` user
  - `.env` file written to `/opt/zettelkasten/compose/.env` (0600)
  - `docker login ghcr.io` succeeds
  - `docker pull ghcr.io/chintanmehta21/zettelkasten-kg-website:<sha>` pulls successfully
  - `deploy.sh` runs:
    - Determines current ACTIVE_COLOR (`blue`), idle is `green`
    - Starts `zettelkasten-green` container on port 10001
    - `healthcheck.sh` polls `http://127.0.0.1:10001/api/health` until 200 (~30 s)
    - Writes new `upstream.snippet` pointing at `zettelkasten-green:10000`
    - `docker exec caddy caddy reload` — graceful config reload
    - Drains and stops `zettelkasten-blue` (which wasn't running anyway on first deploy)
    - Writes `green` to `/opt/zettelkasten/ACTIVE_COLOR`
  - Final log line: `DEPLOY SUCCEEDED. New active color: green, image: ghcr.io/chintanmehta21/zettelkasten-kg-website:<sha>`
- [ ] **22.12** If the deploy fails, copy the last 50 lines of logs and read carefully. Common issues:
  - **"could not connect"** — SSH secret is wrong (`DROPLET_SSH_KEY` missing newlines?)
  - **"unauthorized"** on docker pull — `GHCR_READ_PAT` doesn't have Packages: Read
  - **healthcheck timeout** — container crashed; `docker logs zettelkasten-green` on the droplet to see why (missing env var?)

### Verification

```bash
# From your local machine
ssh -i ~/.ssh/zettelkasten_deploy deploy@<DROPLET_IPV4>
docker ps
cat /opt/zettelkasten/ACTIVE_COLOR
exit
```
Expected:
- `docker ps` shows `caddy` and `zettelkasten-green` both Up
- `ACTIVE_COLOR` contents: `green`

---

# Task 23 — Full smoke test on `https://stage.zettelkasten.in`

**Goal:** Hit every public route to verify the cert provisioned, app is healthy, Supabase round-trip works, HTTP/3 works, IPv6 works, HSTS is present, and the Telegram webhook endpoint is reachable (but not yet switched).

**Time:** 5 minutes.

### Detailed steps

Run each command from your local Windows bash. If any fails, **STOP** and diagnose. Do not proceed to Task 24 until every step is green.

- [ ] **23.1** TLS + HTTP/2 handshake:
  ```bash
  curl -fsS -I https://stage.zettelkasten.in/api/health
  ```
  Expected first line: `HTTP/2 200`. First request may take ~10 seconds (Caddy provisions the cert on first hit).

- [ ] **23.2** Health endpoint JSON:
  ```bash
  curl -fsS https://stage.zettelkasten.in/api/health
  ```
  Expected: `{"status":"ok"}`

- [ ] **23.3** Home page HTML:
  ```bash
  curl -fsS -o /dev/null -w "%{http_code}\n" https://stage.zettelkasten.in/
  ```
  Expected: `200`

- [ ] **23.4** Walk every major route:
  ```bash
  for path in /api/graph /knowledge-graph /home /home/zettels /home/nexus /about /pricing; do
      code=$(curl -fsS -o /dev/null -w "%{http_code}" "https://stage.zettelkasten.in${path}")
      echo "${path} -> ${code}"
  done
  ```
  Expected: every path returns `200`.

- [ ] **23.5** HTTP/3 (QUIC over UDP 443):
  ```bash
  curl --http3 -fsS -I https://stage.zettelkasten.in/api/health
  ```
  Expected: `HTTP/3 200`. If your curl doesn't support `--http3`, open https://stage.zettelkasten.in in Chrome → F12 DevTools → Network tab → refresh → look at the **Protocol** column — should show `h3`.

- [ ] **23.6** IPv6:
  ```bash
  curl -6 -fsS -I https://stage.zettelkasten.in/api/health
  ```
  Expected: `HTTP/2 200`. If your network doesn't route IPv6, this will time out — use https://ipv6-test.com/validate.php?url=https%3A%2F%2Fstage.zettelkasten.in%2Fapi%2Fhealth as an alternative.

- [ ] **23.7** HSTS header:
  ```bash
  curl -fsS -I https://stage.zettelkasten.in/ | grep -i strict-transport-security
  ```
  Expected: `strict-transport-security: max-age=63072000; includeSubDomains; preload`

- [ ] **23.8** Cert issuer check:
  ```bash
  echo | openssl s_client -connect stage.zettelkasten.in:443 -servername stage.zettelkasten.in 2>/dev/null \
      | openssl x509 -noout -issuer -subject -dates
  ```
  Expected:
  - `issuer=C = US, O = Let's Encrypt, CN = R3` (or current LE intermediate)
  - `subject=CN = stage.zettelkasten.in`

- [ ] **23.9** Post a real summarise request:
  ```bash
  curl -fsS -X POST https://stage.zettelkasten.in/api/summarize \
      -H 'Content-Type: application/json' \
      -d '{"url":"https://news.ycombinator.com"}' | head -50
  ```
  Expected: JSON with `title`, `summary`, `tags`, `latency_ms`. A 429 response means you hit the rate limiter — wait 60 s and retry.

- [ ] **23.10** Verify the Supabase write happened:
  ```bash
  curl -fsS https://stage.zettelkasten.in/api/graph | python -c "import sys,json; d=json.load(sys.stdin); print('nodes:',len(d.get('nodes',[])),'links:',len(d.get('links',[])))"
  ```
  Expected: positive node count (should be 1+ higher than before step 23.9).

### Verification

All 10 steps return their expected output.

---

# Task 24 — Blue-green flip rehearsal

**Goal:** Push an empty commit to trigger a second deploy while hitting `/api/health` in a tight loop. Verify zero 502s/503s during the flip.

**Time:** ~6 minutes.

### Detailed steps

- [ ] **24.1** On your local machine:
  ```bash
  cd "C:/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault"
  git commit --allow-empty -m "chore: rehearse blue-green flip"
  git push origin master
  ```
  This triggers `deploy-droplet.yml` automatically (the workflow has `on: push: branches: [master]`).
- [ ] **24.2** Immediately open a **second terminal** and start a tight loop. We want this running **before** the deploy job reaches the flip:
  ```bash
  while true; do
      curl -fsS -w "%{http_code} " https://stage.zettelkasten.in/api/health
      sleep 0.2
  done
  ```
  You should see continuous `200`s streaming across the screen.

  **Wait:** this auto-deploy targets `zettelkasten.in` (the default), not `stage`. For the rehearsal to hit `stage`, you need to trigger manually instead. Do this:

  Stop the empty commit rehearsal (Ctrl+C the loop), revert your approach:

- [ ] **24.3** (Corrected) Instead of an auto-push, use `workflow_dispatch` again against stage:
  - GitHub → Actions → **Deploy to DigitalOcean Droplet** → **Run workflow**
  - **Branch:** `master`
  - **Caddy hostname to deploy:** `stage.zettelkasten.in`
  - Click **Run workflow**
- [ ] **24.4** Approve the production environment when prompted (Task 22.10 steps).
- [ ] **24.5** While the `Deploy` job is running (after pytest + build finish), start the tight-loop curl in a second terminal:
  ```bash
  while true; do
      curl -fsS -w "%{http_code} " https://stage.zettelkasten.in/api/health
      sleep 0.2
  done
  ```
- [ ] **24.6** Watch the stream of status codes during the flip. **Every response should be `200`.** A single `502`, `503`, or `504` means the flip isn't zero-downtime — rollback with `deploy.sh` or investigate.
- [ ] **24.7** When the deploy job shows `DEPLOY SUCCEEDED`, stop the loop (Ctrl+C).
- [ ] **24.8** Verify the color flipped:
  ```bash
  ssh -i ~/.ssh/zettelkasten_deploy deploy@<DROPLET_IPV4> \
      'cat /opt/zettelkasten/ACTIVE_COLOR && cat /opt/zettelkasten/caddy/upstream.snippet'
  ```
  Expected: `ACTIVE_COLOR` is now `blue` (was `green` after Task 22). Snippet references `zettelkasten-blue:10000`.

### Verification

- [ ] Second deploy finished with no HTTP errors in the tight loop.
- [ ] `ACTIVE_COLOR` flipped from `green` to `blue`.

---

# Task 25 — Add apex DNS records (pointing to the droplet)

**Goal:** Flip DNS for `zettelkasten.in` (and `www`) to point at the droplet. Users' requests will start landing on the droplet as DNS propagates (instant for uncached resolvers, up to 60 s for cached).

**Critical:** Render is still running and serving the apex via `<your-app>.onrender.com` — but Render's apex is accessed via the Render URL, not `zettelkasten.in`. If Render has your domain set as a custom domain, remove it first in the Render dashboard before Task 25.2.

**Time:** 3 minutes.

### Detailed steps

- [ ] **25.1** **IF** you previously added `zettelkasten.in` as a custom domain in Render (you probably haven't — the bot was on `<app>.onrender.com`), remove it now:
  - Render dashboard → zettelkasten service → Settings → Custom Domains → find `zettelkasten.in` → click the trash icon → Confirm.
  - If there's no custom domain listed, skip this sub-step.
- [ ] **25.2** Cloudflare → `zettelkasten.in` → **DNS → Records** → **+ Add record**.
- [ ] **25.3** Apex A record:
  - **Type:** `A`
  - **Name:** `@` (Cloudflare shows this as `zettelkasten.in`)
  - **IPv4 address:** `<DROPLET_IPV4>`
  - **Proxy status:** **grey cloud (DNS only)** — NOT orange
  - **TTL:** change from `Auto` to **60 seconds** (manually type `60`). Short TTL gives fast rollback in case of disaster.
  - Click **Save**.
- [ ] **25.4** Apex AAAA record:
  - **Type:** `AAAA`
  - **Name:** `@`
  - **IPv6 address:** `<DROPLET_IPV6>`
  - **Proxy status:** grey cloud
  - **TTL:** `60`
  - Click **Save**.
- [ ] **25.5** `www` CNAME:
  - **Type:** `CNAME`
  - **Name:** `www`
  - **Target:** `zettelkasten.in`
  - **Proxy status:** grey cloud
  - **TTL:** `60`
  - Click **Save**.

### Verification

```bash
dig zettelkasten.in       A     +short
dig zettelkasten.in       AAAA  +short
dig www.zettelkasten.in  CNAME +short
```
Expected:
- First → droplet IPv4
- Second → droplet IPv6
- Third → `zettelkasten.in.`

---

# Task 26 — First deploy targeting the apex hostname

**Goal:** Re-run the deploy workflow with `target_hostname=zettelkasten.in`. This makes the droplet's runtime `WEBHOOK_URL` environment variable match the apex, and makes Caddy provision a new Let's Encrypt cert for the apex on first request.

**Time:** ~8 minutes.

### Detailed steps

- [ ] **26.1** https://github.com/chintanmehta21/Zettelkasten_KG/actions/workflows/deploy-droplet.yml → **Run workflow**.
- [ ] **26.2** Fill in:
  - **Branch:** `master`
  - **Caddy hostname to deploy:** `zettelkasten.in` (this is the default; double-check it says `zettelkasten.in` and NOT `stage.zettelkasten.in`)
- [ ] **26.3** Click **Run workflow**.
- [ ] **26.4** Wait for pytest + build → approve production deploy → watch logs → expect `DEPLOY SUCCEEDED`.
- [ ] **26.5** Trigger the ACME challenge by hitting the apex once:
  ```bash
  curl -fsS https://zettelkasten.in/api/health
  ```
  First call takes ~10 seconds (Caddy solves HTTP-01 challenge in the background). Subsequent calls are fast.
  Expected: `{"status":"ok"}`
- [ ] **26.6** Verify the cert belongs to the apex:
  ```bash
  echo | openssl s_client -connect zettelkasten.in:443 -servername zettelkasten.in 2>/dev/null \
      | openssl x509 -noout -issuer -subject -dates
  ```
  Expected:
  - `issuer=C = US, O = Let's Encrypt, CN = R3`
  - `subject=CN = zettelkasten.in`
  - `notBefore=<today>`, `notAfter=<today + ~90 days>`
- [ ] **26.7** Verify the www → apex 301 redirect:
  ```bash
  curl -fsS -I https://www.zettelkasten.in/
  ```
  Expected: `HTTP/2 301` with `location: https://zettelkasten.in/`

### Verification

- [ ] Cert is for `zettelkasten.in`, issued by Let's Encrypt.
- [ ] `www` → `@` 301 redirect works.

---

# Task 27 — Full smoke test on production apex

**Goal:** Repeat Task 23 but against `zettelkasten.in` instead of `stage.zettelkasten.in`.

**Time:** 5 minutes.

### Detailed steps

- [ ] **27.1** Run every command from Task 23 but replace `stage.zettelkasten.in` with `zettelkasten.in`.
- [ ] **27.2** All 10 checks must return the expected output.
- [ ] **27.3** Do NOT proceed to Task 28 if any check fails. Diagnose on the droplet:
  ```bash
  ssh -i ~/.ssh/zettelkasten_deploy deploy@<DROPLET_IPV4>
  docker ps
  docker logs zettelkasten-blue --tail 100         # or zettelkasten-green, whichever is active
  docker logs caddy --tail 50
  cat /opt/zettelkasten/logs/deploy.log
  ```

### Verification

- [ ] Every Task 23 check passes on the production hostname.

---

# Task 28 — Swap the Telegram webhook to the new host

**Goal:** Tell Telegram to send all bot updates to `https://zettelkasten.in/telegram/webhook` instead of the Render URL. This is the cutover moment — Telegram stops talking to Render and starts talking to the droplet.

**Time:** 2 minutes.

### Detailed steps

- [ ] **28.1** In your local Windows bash, export the token and secret into shell variables (NOT into any file):
  ```bash
  export TOKEN='<TELEGRAM_BOT_TOKEN from Secrets Vault>'
  export SECRET='<WEBHOOK_SECRET from Secrets Vault — the same one you added in Task 15>'
  ```
- [ ] **28.2** Call Telegram's `setWebhook` API:
  ```bash
  curl -fsS "https://api.telegram.org/bot${TOKEN}/setWebhook" \
      --data-urlencode "url=https://zettelkasten.in/telegram/webhook" \
      --data-urlencode "secret_token=${SECRET}" \
      --data-urlencode "drop_pending_updates=false"
  ```
  Expected response:
  ```json
  {"ok":true,"result":true,"description":"Webhook was set"}
  ```

  **Why `drop_pending_updates=false`:** if any updates queued up in the tiny window between removing the Render webhook and setting the new one, we still want them processed.

- [ ] **28.3** Verify the webhook is actually set to the new URL:
  ```bash
  curl -fsS "https://api.telegram.org/bot${TOKEN}/getWebhookInfo" | python -m json.tool
  ```
  Expected JSON (key fields):
  ```json
  {
    "ok": true,
    "result": {
      "url": "https://zettelkasten.in/telegram/webhook",
      "has_custom_certificate": false,
      "pending_update_count": 0,
      "max_connections": 40,
      "ip_address": "<droplet ipv4>",
      "last_error_date": 0,              ← absent or 0
      "last_error_message": ""           ← absent
    }
  }
  ```
- [ ] **28.4** Send a real test command to the bot from Telegram. Open the bot chat on your phone and paste any URL (e.g. https://github.com/anthropics/anthropic-sdk-python). Within 2 seconds the bot should reply with "Processing..." → "Saved as note ..." (or similar, depending on your flow).
- [ ] **28.5** On the droplet, tail the active container logs and confirm the webhook request landed:
  ```bash
  ACTIVE=$(ssh -i ~/.ssh/zettelkasten_deploy deploy@<DROPLET_IPV4> 'cat /opt/zettelkasten/ACTIVE_COLOR')
  ssh -i ~/.ssh/zettelkasten_deploy deploy@<DROPLET_IPV4> "docker logs zettelkasten-${ACTIVE} --tail 100 2>&1 | grep -i webhook"
  ```
  Expected: at least one log line mentioning a webhook update or telegram.
- [ ] **28.6** Clear the shell variables so they don't leak into shell history:
  ```bash
  unset TOKEN SECRET
  ```

### Verification

- [ ] `getWebhookInfo` shows the new URL.
- [ ] Bot replies within 2 seconds to a real command.
- [ ] Droplet logs show the webhook hit.

---

# Task 29 — Pause the Render service (keep as rollback)

**Goal:** Stop Render from serving traffic, but don't delete the service yet — it's your rollback for the next 7 days.

**Time:** 2 minutes.

### Detailed steps

- [ ] **29.1** https://dashboard.render.com → click on the zettelkasten service.
- [ ] **29.2** Left sidebar → **Settings**.
- [ ] **29.3** Scroll all the way to the bottom → **Suspend Web Service** section.
- [ ] **29.4** Click **Suspend Web Service** (red button).
- [ ] **29.5** Confirmation dialog → type the service name to confirm → **Suspend**.
- [ ] **29.6** The service status flips to **Suspended**. Render stops billing for compute (you still pay for any add-ons).

### Verification

```bash
curl -fsS -m 5 https://<your-render-url>/api/health || echo "Render is paused (expected)"
```
Expected: `Render is paused (expected)` — curl fails with timeout or connection refused.

```bash
# Droplet is taking all the traffic
ssh -i ~/.ssh/zettelkasten_deploy deploy@<DROPLET_IPV4> 'tail -30 /opt/zettelkasten/logs/caddy-access.log 2>/dev/null || docker logs caddy --tail 30'
```
Expected: real user requests (including Telegram webhook calls) landing on the droplet.

---

# Task 30 — Raise apex DNS TTLs back to 3600 s

**Goal:** Now that the cutover is complete and stable, raise TTLs so Cloudflare doesn't hammer your nameservers with a 60-second polling interval. A 1-hour TTL is fine long-term.

**Time:** 2 minutes.

### Detailed steps

- [ ] **30.1** Cloudflare → `zettelkasten.in` → **DNS → Records**.
- [ ] **30.2** Find the apex `A` record → click the **Edit** icon (pencil) on the right.
- [ ] **30.3** Change **TTL** from `60` to `3600` (or choose `Auto`, which Cloudflare treats as ~5 min but managed). Click **Save**.
- [ ] **30.4** Repeat for the apex `AAAA` record: edit → TTL `3600` → Save.
- [ ] **30.5** Repeat for the `www` CNAME: edit → TTL `3600` → Save.

### Verification

```bash
dig zettelkasten.in A | grep -A1 'ANSWER SECTION'
```
Expected: the TTL on the second line (after the A record) is ~3600 (or decrementing toward it as caches refresh).

---

# Task 31 — Delete the staging DNS records

**Goal:** We don't need the `stage` hostname long-term. Delete the records.

**Time:** 1 minute.

### Detailed steps

- [ ] **31.1** Cloudflare → `zettelkasten.in` → **DNS → Records**.
- [ ] **31.2** Find the `stage` A record → **Edit** → **Delete** → confirm.
- [ ] **31.3** Find the `stage` AAAA record → **Edit** → **Delete** → confirm.

### Verification

```bash
dig stage.zettelkasten.in +short
```
Expected: empty (NXDOMAIN).

---

# Task 32 — Set up BetterStack uptime monitors

**Goal:** External monitoring pinging the droplet every 30 s from multiple regions. Alerts on 2 consecutive failures via email and Telegram.

**Time:** 10 minutes.

### Detailed steps

- [ ] **32.1** Sign up / log in to https://uptime.betterstack.com
- [ ] **32.2** Top nav → **Monitors** → green **Create monitor** button.
- [ ] **32.3** **Monitor 1 — API health**:
  - **Monitor type:** HTTP(s)
  - **URL:** `https://zettelkasten.in/api/health`
  - **Check frequency:** `30 seconds`
  - **Request method:** `GET`
  - **Expected HTTP status:** `200`
  - **Regions to check from:** select 3 — e.g. **India (Mumbai)**, **United States (Virginia)**, **Germany (Frankfurt)**
  - **Alert after:** `2 consecutive failed checks`
  - **Recovery period:** `1 successful check`
  - **Name:** `Zettelkasten API health`
  - Click **Create monitor**.
- [ ] **32.4** Click **Create monitor** again → **Monitor 2 — Home page**:
  - **URL:** `https://zettelkasten.in/`
  - **Check frequency:** `60 seconds`
  - **Expected HTTP status:** `200`
  - **Regions:** India primary
  - **Alert after:** `2 consecutive failed checks`
  - **Name:** `Zettelkasten home page`
  - Click **Create monitor**.
- [ ] **32.5** Left nav → **Integrations** → add your alert channels:
  - **Email:** add `chintanoninternet@gmail.com` → verify via email link
  - **Telegram:** click **Telegram** integration → it gives you a bot to add to your Telegram chat → follow the instructions → verify you receive a test message
- [ ] **32.6** For each monitor, ensure both channels are configured:
  - Open the monitor → **Alert channels** tab → tick Email and Telegram
- [ ] **32.7** Test alerts: on each monitor, click **Send test alert**. You should receive one email and one Telegram message for each monitor within 30 seconds.

### Verification

- [ ] Both monitors show status `Up` on the BetterStack dashboard.
- [ ] Test alerts received via email and Telegram.

---

# Task 33 — Post-cutover hardening checklist

**Goal:** Verify every hardening spec item is actually in effect. If any fails, go back and fix before considering the migration complete.

**Time:** 10 minutes.

### Detailed steps

Run each of the following from your local Windows bash. Every one should pass.

- [ ] **33.1** DNSSEC active:
  ```bash
  dig zettelkasten.in +dnssec | grep -i 'flags:.*ad'
  ```
  Expected: a line containing `ad`.

- [ ] **33.2** CAA active:
  ```bash
  dig zettelkasten.in CAA +short
  ```
  Expected: `0 issue "letsencrypt.org"`

- [ ] **33.3** HTTP/3 active:
  ```bash
  curl --http3 -fsS -I https://zettelkasten.in/api/health 2>&1 | head -1
  ```
  Expected: `HTTP/3 200`

- [ ] **33.4** IPv6 active:
  ```bash
  curl -6 -fsS -I https://zettelkasten.in/api/health | head -1
  ```
  Expected: `HTTP/2 200`

- [ ] **33.5** HSTS header present:
  ```bash
  curl -fsS -I https://zettelkasten.in/ | grep -i strict-transport
  ```
  Expected: `strict-transport-security: max-age=63072000; includeSubDomains; preload`

- [ ] **33.6** BetterStack dashboard: both monitors **green** for at least 10 minutes.

- [ ] **33.7** Telegram `getWebhookInfo` points at new host:
  ```bash
  export TOKEN='<TELEGRAM_BOT_TOKEN>'
  curl -fsS "https://api.telegram.org/bot${TOKEN}/getWebhookInfo" | python -m json.tool | grep -A1 '"url"'
  unset TOKEN
  ```
  Expected: `"url": "https://zettelkasten.in/telegram/webhook"`

- [ ] **33.8** systemd unit enabled and active:
  ```bash
  ssh -i ~/.ssh/zettelkasten_deploy deploy@<DROPLET_IPV4> \
      'sudo systemctl is-enabled zettelkasten.service && sudo systemctl is-active zettelkasten.service'
  ```
  Expected: both `enabled` and `active`. If `sudo` prompts for a password, the bootstrap didn't give deploy passwordless sudo — add it manually:
  ```bash
  ssh root@<DROPLET_IPV4>   # from DO console if root SSH is disabled
  echo 'deploy ALL=(ALL) NOPASSWD: /bin/systemctl is-enabled zettelkasten.service, /bin/systemctl is-active zettelkasten.service, /sbin/reboot' > /etc/sudoers.d/99-deploy
  chmod 0440 /etc/sudoers.d/99-deploy
  ```

- [ ] **33.9** **Reboot test** — the most important one. Proves systemd brings everything back automatically after a droplet restart:
  ```bash
  ssh -i ~/.ssh/zettelkasten_deploy deploy@<DROPLET_IPV4> 'sudo reboot'
  ```
  SSH disconnects. Wait **90 seconds**, then:
  ```bash
  curl -fsS https://zettelkasten.in/api/health
  ```
  Expected: `{"status":"ok"}`. The site came back with no manual intervention.

- [ ] **33.10** (Optional but recommended) Submit `zettelkasten.in` to the HSTS preload list:
  - Go to https://hstspreload.org/
  - Enter `zettelkasten.in` → click **Check**
  - If all eligibility checks pass, click **Submit**. Once included, `zettelkasten.in` is hardcoded into major browsers as HTTPS-only forever. **Only do this if you are 100% sure you will never go back to HTTP**.

- [ ] **33.11** Update the README's deployment section to point at the new architecture. This is the **only** code commit in this walkthrough.

  Open `README.md` in your editor. Find the existing "Deployment" or "Render" section. Replace it with:
  ```markdown
  ## Deployment

  Production runs on a DigitalOcean Droplet (BLR1, Premium AMD $7/mo) behind Caddy with blue-green deploys via GitHub Actions. See [`docs/superpowers/specs/2026-04-09-render-to-digitalocean-migration-design.md`](docs/superpowers/specs/2026-04-09-render-to-digitalocean-migration-design.md) for architecture and [`docs/superpowers/plans/2026-04-09-render-to-digitalocean-migration.md`](docs/superpowers/plans/2026-04-09-render-to-digitalocean-migration.md) for the implementation.
  ```

  Commit and push:
  ```bash
  cd "C:/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault"
  git add README.md
  git commit -m "docs(readme): point deployment section at digitalocean spec and plan"
  git push origin master
  ```
  This push will auto-trigger `deploy-droplet.yml`. Approve the production environment and verify the new deploy goes green — this is the final end-to-end regression test of the whole pipeline.

### Verification

- [ ] All 11 sub-tasks pass.
- [ ] Droplet survives a reboot cleanly.
- [ ] Final README deploy went green.

---

# Task 34 — T + 7 days: delete the Render service

**Goal:** Seven days after cutover, Render has proven unnecessary as a rollback target. Delete it to stop being charged for any lingering resources.

**When to do this:** wait **at least** 7 days after Task 29 (pause Render). Confirm BetterStack shows 99.9 %+ uptime for the past 7 days before deleting.

**Time:** 2 minutes.

### Detailed steps

- [ ] **34.1** Verify droplet stability — BetterStack dashboard → **Reports → Uptime**. Select the last 7 days. Should show ≥ 99.9 %.
- [ ] **34.2** Log in to https://dashboard.render.com
- [ ] **34.3** Click the suspended zettelkasten service (may be under **Suspended services**).
- [ ] **34.4** Left sidebar → **Settings** → scroll to the very bottom → **Delete Web Service**.
- [ ] **34.5** Red confirmation dialog → type the service name → click **Delete**. **This is irreversible.**
- [ ] **34.6** The service disappears from the Render dashboard.
- [ ] **34.7** Optional cleanup — if you have old Render-specific env vars in `ops/.env.example` or `ops/config.yaml`, remove them in a follow-up commit. Not urgent.

### Verification

- [ ] Render dashboard no longer lists the zettelkasten service.
- [ ] `zettelkasten.in` still serves `{"status":"ok"}` on `/api/health`.

---

## Migration complete

At this point:
- Production traffic flows via Cloudflare DNS → droplet IPv4/IPv6 → Caddy → the active-color container
- Zero-downtime blue-green deploys are in place via `workflow_dispatch` or `git push origin master`
- Every deploy requires your manual approval through the GitHub `production` environment
- DNSSEC, CAA, HSTS, HTTP/3, IPv6 all active
- BetterStack monitors ping from 3 regions every 30 s
- Telegram webhook posts to `/telegram/webhook` with `X-Telegram-Bot-Api-Secret-Token` header auth
- Supabase Free tier unchanged; `SUPABASE_SERVICE_ROLE_KEY` never touched the droplet
- Render is deleted

Cost: **$7/mo** (droplet) + **$0** (Cloudflare Free, Supabase Free, BetterStack Free, GitHub Actions minutes on free tier).

---

## Appendix A — What to do if something goes wrong

### Rollback scenarios

**Scenario 1: Deploy fails during Task 22 or 26**
- The failure is logged in GitHub Actions `Deploy` job
- SSH to droplet: `ssh -i ~/.ssh/zettelkasten_deploy deploy@<DROPLET_IPV4>`
- Inspect: `docker ps -a`, `docker logs <container>`, `cat /opt/zettelkasten/logs/deploy.log`
- Rollback to the previous good image: `bash /opt/zettelkasten/deploy/rollback.sh`
- This script flips Caddy back to the last known good color and stops the broken one

**Scenario 2: Cutover broken (users reporting errors after Task 25 / 28)**
- Fast DNS rollback: Cloudflare DNS → edit apex A and AAAA → change IPs back to Render's (look up from Render dashboard → Settings → Outbound IPs). With TTL 60, traffic rolls back in ~60 s.
- Resume Render service: dashboard → Settings → Resume Web Service.
- Telegram webhook rollback: call `setWebhook` again with the old Render URL.

**Scenario 3: Droplet unreachable**
- DigitalOcean dashboard → droplet → **Access → Launch Droplet Console** (emergency web-based root console, bypasses SSH).
- Investigate with `systemctl status zettelkasten.service`, `journalctl -u zettelkasten.service -n 100`.
- Worst case: `docker compose -f /opt/zettelkasten/compose/docker-compose.caddy.yml restart` and `docker compose -f /opt/zettelkasten/compose/docker-compose.<ACTIVE_COLOR>.yml restart`.

### Emergency contacts

- **DigitalOcean support:** https://cloud.digitalocean.com/support/tickets/new — 24/7, free tier eligible.
- **Cloudflare support:** Free tier has community support only. Use https://community.cloudflare.com.
- **GoDaddy support:** 1800 121 1222 (India toll-free).

---

## Appendix B — Where each value ends up

Quick reference for everything you paste somewhere during this walkthrough.

| Secret / value | Generated in | Lives in |
|---|---|---|
| Cloudflare nameservers (2) | Task 4 | GoDaddy → Nameservers (Task 5) |
| Cloudflare DS record | Task 7 | GoDaddy → DNSSEC (Task 8) |
| `DROPLET_IPV4` | Task 10 | GitHub Environment secret `DROPLET_HOST` (Task 15) + Cloudflare A records (Tasks 21, 25) |
| `DROPLET_IPV6` | Task 10 | Cloudflare AAAA records (Tasks 21, 25) |
| Deploy SSH public key | Task 11 | Droplet `/home/deploy/.ssh/authorized_keys` (via `DEPLOY_PUBKEY` env var in Task 17) |
| Deploy SSH private key | Task 11 | GitHub Environment secret `DROPLET_SSH_KEY` (Task 15) |
| `GHCR_READ_PAT` | Task 12 | GitHub Environment secret `GHCR_READ_PAT` (Task 15) |
| `WEBHOOK_SECRET` | Task 13 | GitHub Environment secret `WEBHOOK_SECRET` (Task 15) + Telegram `setWebhook` call (Task 28) |
| Render env var values | Task 1 | GitHub Environment secrets (Task 15, 1:1 except renamed `GITHUB_TOKEN` → `GITHUB_TOKEN_FOR_NOTES`) |
| `SUPABASE_SERVICE_ROLE_KEY` | (do not touch) | **NOWHERE** — stays Windows-only |
