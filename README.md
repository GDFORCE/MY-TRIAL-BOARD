# My Trial Board — Module 01 runnable reference application

A full-stack **local reference build** based on `MTB_Module_01_Registration_Login_Invitation_BRD.docx` (29 October 2026). Styling references the supplied Navy `#14213D`, Cream `#F4EDE0`, Coral `#FF685B` screenshot.

## Run it

Requires Python 3.11+.

```bash
cd mtb-registration-app
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
# Windows PowerShell: $env:MTB_DEV_MODE="1"
# Windows PowerShell: $env:MTB_SECRET="a-long-random-local-secret"
export MTB_DEV_MODE=1
export MTB_SECRET="replace-with-a-long-random-secret"
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

### Tests

- `pytest` runs the fast server tests in `tests/`.
- `pytest tests_e2e` runs the browser tests (Playwright, using the installed Google Chrome; `pip install -r requirements-e2e.txt` first). They click through every flow — registration for each organization type, validation, sign-in, lockout and unlock, password recovery, invitations, hospitals and SMOs, PIs with several SMOs, audit trail, MTB Admin console — on their own copy of the site with an empty temporary database, so real data is never touched. A screenshot of any failing test is saved in `tests_e2e/failures/`.

### Other settings (in `.env`)

- `MTB_SESSION_HOURS` — how long a sign-in lasts (default 8). The session also ends when the browser closes.
- `MTB_FORCE_HTTPS` — redirect plain http to https and send HSTS. On by default when `MTB_DEV_MODE` is off; local addresses (127.0.0.1, localhost) are never redirected.
- `MTB_ADMIN_EMAILS` — comma-separated MTB Admins. Create a login with `python create_admin.py email "First Last"`.
- `BREVO_API_KEY`, `MTB_MAIL_FROM`, `MTB_MAIL_FROM_NAME`, `MTB_APP_URL` — real email through Brevo (free plan: 300 emails a day); see `mailer.py`. With the key empty, nothing is sent and messages only reach the test inbox. The sender address must be verified in Brevo. The MTB Admin console shows whether delivery is working and can send a test email. SMS is not connected yet.

### My Profile and CV auto-fill (Module 02)

Every person has one profile (`mtb_profile.py`, `static/profile.js`) built from `MTB_Profile_BRD` sections 1-25, except Clinical Trial Experience (section 10), which is a later module.

- **Wizard** with 16 steps (Basic Information to Declaration), saved step by step, with a sign-in reminder while the profile is incomplete.
- **CV auto-fill.** Add `OPENAI_API_KEY` to `.env`. The CV (PDF, DOC or DOCX) is sent to the OpenAI Responses API as a file, so any layout, scanned pages included, can be read. The answer must match a strict JSON schema built from the same section definitions as the forms, is cleaned again on the server, and is shown as a preview where each entry is accepted, edited or rejected. Nothing is saved until the person presses *Save confirmed fields*. Verified name, email and phone are never overwritten; duplicates and conflicts are flagged.
- `MTB_OPENAI_MODEL` (default `gpt-6.1-terra`), `MTB_OPENAI_REASONING` (optional) and `OPENAI_BASE_URL` (proxy or test stub) are optional. Without a key the feature is switched off.
- **E-signature.** The declaration is signed with the typed full name and the account password; it is sealed and written to the audit trail.
- **Export as CV** to PDF and DOCX (Professional and Clinical Research templates; the trial-experience template is greyed out until that section exists). Aadhaar, identity documents and uploaded files are never exported.
- **Teammates** can see the professional sections the owner leaves switched on (*Team profiles* tab). Contact details, address, identity and files are never shown. Organization Admin status gives no extra access.
- Uploaded files live in `uploads/profile/` and are served only to their owner.

The browser tests use a stand-in for OpenAI (`tests_e2e/fake_openai.py`), so they never call the real service.

### Google address autofill (optional)

Typing an organization or hospital name suggests matches and fills in address, city, state, PIN, phone and website.

1. In Google Cloud Console, create an API key and enable **Maps JavaScript API** and **Places API (New)** (billing must be enabled on the project).
2. Restrict the key: *Application restrictions → Websites* → add `http://127.0.0.1:8000/*` (plus your real domain later); *API restrictions* → the two APIs above.
3. Start the server with the key:
   - PowerShell: `$env:MTB_GOOGLE_MAPS_KEY="your-key"`
   - macOS/Linux: `export MTB_GOOGLE_MAPS_KEY="your-key"`

Without a key the hospital search still suggests records already on MTB; the Google suggestions are simply skipped.

### Duplicate organizations and ownership claims

- **Live duplicate check.** While step 1 of registration is filled in, `/api/org-check` looks for the same organization. *Already registered* (same name and city, ignoring case and punctuation, or the same Google place) blocks the registration. *Possible match* (similar name after removing words like Pvt/Ltd/Hospital, same acronym, same website domain or same contact number) must be confirmed as a different organization. City spellings such as Bangalore/Bengaluru count as the same city. The server repeats the check on submit.
- **Request to join.** Sends the existing organization's admins a request without revealing who they are. The admin sees it on the dashboard and can invite or dismiss it.
- **Unverified registrations expire** after `MTB_PENDING_HOURS` (default 48), so they stop blocking the name and email.
- **"This is my organization" (ownership claim).** The claimant registers against the existing record instead of creating a duplicate. After email and phone verification:
  1. If the claimant's official email domain matches the organization's website domain (and the current admin doesn't use that domain), the claim is approved immediately.
  2. Otherwise the current admins have `MTB_CLAIM_WINDOW_DAYS` (default 7) to object from their dashboard. With no objection the claim is approved automatically.
  3. Objections and competing claims go to an MTB Admin (`MTB_ADMIN_EMAILS`, comma-separated) for review on the dashboard.
  An approved claim makes the claimant Organization Admin and ends the previous admins' access.
- **Provisional hospitals.** When a Site registers and an SMO has already added it, the Site claims that record with the same rules. The objectors are the linked SMOs' admins.
- **Optional phone proof.** With `MTB_GOOGLE_SERVER_KEY` (a server key restricted by IP, with Places API (New) enabled), a claimant can also prove ownership with a code sent to the phone number Google lists for the place. That key is also used to read the official website.

Open **http://127.0.0.1:8000**. Register an organization, view the generated OTPs with the **OTP outbox** development button, verify both channels, and log in. For invitations in development, copy the displayed invitation URL; use a separate user with the matching email to accept it. Database is created as `mtb.sqlite3` on first launch.

## Implemented

- Responsive homepage, step-by-step organization registration, organization categories, authorized representative, password checks, consent records, CAPTCHA demonstration, email and phone OTP challenge, and account activation.
- Argon2 password hashes, HttpOnly signed session cookie, server-side session revocation, CSRF header on authenticated writes, 3-failure lockout, recovery OTP and password reset, basic audit log.
- Dashboard with organization selector, membership list, invitations and audit view.
- Organization Admin invitations, existing-member invite acceptance/rejection via expiring one-time opaque links, and team membership scope.
- SMO hospital add/search/deduplication, provisional hospital affiliations, SMO PI invitations (for existing MTB users), multiple SMO–PI relationships, and separate authorization boundaries.
- SQLite persistence and HTTP API. No confidential clinical trial or patient records are stored by this module.

## Important limitations: not production deployable yet

This is a working reference implementation **not a production-certified identity system**. Production launch requires additional work:

1. Real email and SMS service integrations, queue/retry/outbox worker, delivery callbacks, fraud prevention and per-IP/global rate limits. Development outbox is intentionally disabled outside `MTB_DEV_MODE=1`.
2. Replace the demonstration CAPTCHA with verified server-side Turnstile/reCAPTCHA (the current challenge/expected value can be supplied by the browser and **must not be trusted**).
3. Harden the implemented invitation-first **new user account creation**; add secure recovery when official email is lost, admin bulk import of PDF/Word/Excel with review, MTB-admin operations, invite revocation and expiry management.
4. Add legal document uploading, safe storage and scanning, lawful identity-verification vendor workflow (no direct UIDAI assumption), real email/SMS delivery of claim and join-request notices (currently the dev outbox), a proper MTB Admin role instead of the `MTB_ADMIN_EMAILS` list, and a background job for claim deadlines and expiry (currently run on each request).
5. Enforce server-side failed login logging in a standalone transaction, protect against enumeration and automated guesses, normalize error outcomes, improve session/device policies, optional MFA, verified alternate email, configurable OTP limits and 24-hour phone caps.
6. Adopt PostgreSQL with transactional migrations and constraints, background tasks, secret manager, TLS reverse proxy, secure cookies, observability, backups, data retention policy, immutable audit sink, penetration testing, integration/end-to-end tests and deployment hardening.
7. Add complete role-based trial assignments and portfolio confidentiality — specifically **do not infer trial access from hospital, PI or org affiliation**. No trial workspace is implemented here.
8. Implement production legal/privacy policies (including DPDP), accessibility WCAG testing, localization, error monitoring, and formal QA.

## Data and security notes

Aadhaar numbers and certificates are **not** collected in this prototype, pending legal provider integration. It stores hashed passwords and hashed OTPs, never plaintext credentials in the database. In dev mode, messages deliberately expose OTPs in the test outbox for local testing only. Never expose a development server to the public internet.

## BRD coverage snapshot

| BRD section | Status |
|---|---|
| 2 Registration entry + instructions | Done: Register Organization entry, on-form instructions, Admin responsibilities, live duplicate check (exact + likely matches), request to join, ownership claims, expiry of unverified registrations. Geotagging statement is "to be discussed" in the BRD |
| 3 Organization details | Done: all fields, Sponsor multi-select, CRO/Site single-select, "Others – specify", legal document upload (PDF/PNG/JPG ≤ 5 MB, type-checked). **Pending:** MTB Admin approval of proposed global "Others" options (3.3.2–3) |
| 4 SMO hospital addition | Done: all fields, MTB directory search + Google autofill, dedup by name+city, declaration for new provisional sites, approval for registered hospitals, a Site claiming the provisional record an SMO added. **Pending:** fuzzy matching when SMOs add hospitals (4.2.4), hospital profile completion by the site |
| 5 Hospital / PI affiliations | Done for the authorization rules in this module (no trial data exists yet) |
| 6 Authorized person | Done, incl. live password rules and show/hide. **Pending:** Aadhaar via an authorized provider (not collected) |
| 7 Declarations | Done: authority, accuracy/update undertaking, Terms + Privacy Notice, each stored with timestamp and version. Legal texts are placeholders |
| 8 Verification | Done: email/phone/alternate-email OTP with BRD limits (5/3 attempts, 5 per hour email, 3 per 30 min + 10 per day SMS), verified timestamps. **Pending:** real email/SMS delivery, real CAPTCHA |
| 9 Account creation | Done: exact success message + Login button |
| 10 Login | Done: Login enabled when fields filled, show/hide, generic errors (Remember Me removed: 8-hour sessions that end when the browser closes), warnings after 1st/2nd failure, CAPTCHA after 1st, lock after 3rd, device/IP in audit, no-store caching. HTTPS is a deployment item |
| 11 Recovery + unlock | Done: recovery only through verified channels, OTP unlock |
| 12–14 Invitations | Done: member and SMO-PI invitations with BRD fields, new vs existing users. **Pending:** bulk upload (PDF/Word/Excel) with review |
| 15 MTB Admin | Partly: MTB Admin console (analytics, people, organizations, activity log; block, unblock, unlock, sign out, delete). Admins are listed in `MTB_ADMIN_EMAILS`; create a login with `python create_admin.py email "First Last"`. **Pending:** Add New and bulk upload (PDF/Word/Excel) invitations |
| 16 Multiple affiliations | Done: one identity, per-org roles, workspace switch |
| 17 Inactivation and recovery | Done: Admin deactivates a membership in their org only. **Pending:** account suspend/deactivate states, loss-of-official-email recovery (17.3) |
| 18 Audit | Done for listed events. **Pending:** tamper-proof audit store, previous/new values |
| 19–20 Rules and flows | Done for this module; trial assignment belongs to a later module |

**Invitation onboarding update:** A new user can now open an invitation link, choose **Create your invited account**, complete email/phone verification, sign in, return to the same invitation URL and accept it. For logged-in users the invitation page opens directly. This replaces the earlier limitation regarding new-user invitation signup, but outbound delivery and comprehensive invitation management still need production integrations.
