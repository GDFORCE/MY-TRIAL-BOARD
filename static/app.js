const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)], app = $('#app');
const state = {
  page: 'home', step: 0, registrationId: null, hasAlt: false,
  verify: { email: false, phone: false, alt_email: false },
  me: null, org: null, dash: null, tab: 'overview', csrf: '', dev: false, mapsKey: '', modal: null,
  inviteToken: new URLSearchParams(location.hash.slice(1)).get('invite') || new URLSearchParams(location.search).get('invite'),  // links use #invite= so the token never reaches server logs
  login: { failed: 0, locked: false, message: '', tone: 'warn', email: '' },
};
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
let toastTimer;
const toast = message => {
  const el = $('#toast');
  el.textContent = message;
  el.classList.remove('show'); void el.offsetWidth; el.classList.add('show');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => el.classList.remove('show'), 4500);
};
async function api(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...(opts.body ? { 'X-CSRF-Token': state.csrf } : {}) };
  const res = await fetch('/api' + path, { ...opts, headers: { ...headers, ...opts.headers } });
  let json = {};
  try { json = await res.json(); } catch {}
  if (!res.ok) {
    const d = json.detail, structured = d && typeof d === 'object' && !Array.isArray(d);
    const err = Error(typeof d === 'string' ? d : structured && d.message ? d.message : 'Request failed');
    err.status = res.status; err.data = structured ? d : null; throw err;
  }
  return json;
}
// BRD 10.4.3: a page restored from the browser's back/forward cache reloads, so the session is checked again.
window.addEventListener('pageshow', e => { if (e.persisted) location.reload(); });
async function boot() {
  try { const c = await api('/config'); state.dev = c.dev_mode; state.mapsKey = c.maps_key || ''; state.claimWindowDays = c.claim_window_days; state.memberRoles = c.member_roles || {}; state.piRoles = c.pi_roles; } catch {}
  if (state.mapsKey) MTBPlaces.load(state.mapsKey);
  try {
    const me = await api('/me');
    state.me = me; state.csrf = me.csrf;
    if (state.inviteToken) { state.page = 'invite'; render(); }
    else await enterWorkspace(false);
  } catch { state.page = state.inviteToken ? 'invite' : 'home'; render(); }
}

/* ---------- Option lists (BRD 3.1, 3.2, 4.1, 6, 13, 14) ---------- */
const OPTS = {
  orgTypes: ['Sponsor', 'CRO', 'SMO', 'Site / Hospital / Institution'],
  categories: {
    Sponsor: ['Pharmaceutical', 'Biotechnology', 'Medical Device', 'Academic Institution', 'Government Agency', 'CRO as Sponsor', 'Hospital/Healthcare Institution', 'Investigator-Initiated', 'Foundation/Trust'],
    CRO: ['Clinical Trials', 'BA-BE', 'Clinical Trials and BA-BE', 'Biotechnology', 'HEOR', 'Preclinical', 'Bioanalytical'],
    'Site / Hospital / Institution': ['Private', 'Government', 'Trust', 'Academic'],
  },
  hospitalTypes: ['Government', 'Private', 'Trust', 'Academic'],
  salutations: ['Dr.', 'Prof.', 'Mr.', 'Ms.', 'Mrs.'],
  genders: ['Male', 'Female', 'Other'],
  roles: ['PI', 'Research Team'],
};
const PHONE = 'inputmode="tel" pattern="\\+?[0-9 \\(\\)\\-]{7,20}" title="Use 7–15 digits; +, spaces, brackets and dashes are allowed"';

/* ---------- Form building blocks ---------- */
const REQ = ' <span class="req">*</span>';
function field(label, id, o = {}) {
  const { type = 'text', required = false, placeholder = '', value = '', full = false, help = '', attrs = '' } = o;
  return `<div class="field ${full ? 'full' : ''}"><label for="${id}">${label}${required ? REQ : ''}</label><input id="${id}" name="${id}" type="${type}" placeholder="${esc(placeholder)}" value="${esc(value)}" ${required ? 'required' : ''} ${attrs}>${help ? `<small class="help">${help}</small>` : ''}<small class="err" aria-live="polite"></small></div>`;
}
function select(label, id, options, o = {}) {
  const { required = false, full = false, other = false, value = '', help = '' } = o;
  const isOther = other && String(value).startsWith('Others');
  const otherText = isOther ? String(value).replace(/^Others:?\s*/, '') : '';
  return `<div class="field ${full ? 'full' : ''}"><label for="${id}">${label}${required ? REQ : ''}</label><select id="${id}" name="${id}" ${required ? 'required' : ''} ${other ? `data-other="${id}_other"` : ''}><option value="">Select ${label.toLowerCase()}</option>${options.map(x => `<option ${x === value ? 'selected' : ''}>${esc(x)}</option>`).join('')}${other ? `<option value="Others" ${isOther ? 'selected' : ''}>Others (specify)</option>` : ''}</select>${other ? `<input id="${id}_other" class="other-input ${isOther ? '' : 'hidden'}" placeholder="Please specify" value="${esc(otherText)}" ${isOther ? 'required' : ''} maxlength="80" aria-label="${label}: please specify">` : ''}${help ? `<small class="help">${help}</small>` : ''}<small class="err" aria-live="polite"></small></div>`;
}
function readSelect(id) {
  const v = $('#' + id)?.value || '';
  return v === 'Others' ? 'Others: ' + ($('#' + id + '_other')?.value.trim() || '') : v;
}
// Pill-style choices. single=true gives one choice (radio), otherwise "select all that apply" (checkbox).
function chips(label, name, options, values = [], { single = false, msg = 'Select at least one option.' } = {}) {
  const others = values.find(v => v.startsWith('Others'));
  const type = single ? 'radio' : 'checkbox';
  return `<fieldset class="field full chip-field" id="${name}" data-msg="${esc(msg)}"><legend>${label}${REQ} <small class="help">${single ? 'Select one' : 'Select all that apply'}</small></legend><div class="chip-row">${options.map(x => `<label class="chip"><input type="${type}" name="${name}" value="${esc(x)}" ${values.includes(x) ? 'checked' : ''}><span>${esc(x)}</span></label>`).join('')}<label class="chip"><input type="${type}" name="${name}" value="Others" data-other="${name}_other" ${others ? 'checked' : ''}><span>Others (specify)</span></label></div><input id="${name}_other" class="other-input ${others ? '' : 'hidden'}" placeholder="Please specify" value="${esc(others ? others.replace(/^Others:?\s*/, '') : '')}" ${others ? 'required' : ''} maxlength="80" aria-label="${esc(label)}: please specify"><small class="err" id="${name}_err" aria-live="polite"></small></fieldset>`;
}
// Make "select at least one" part of normal form validation, so it is reported with the other fields.
function syncChips(name) {
  const field = $('#' + name), boxes = $$(`#${name} .chip input`);
  if (!boxes.length) return;
  boxes[0].setCustomValidity(boxes.some(b => b.checked) ? '' : field.dataset.msg);
  // Show the "please specify" box only while "Others" is chosen (a radio gets no change event when deselected).
  const other = boxes.find(b => b.value === 'Others'), inp = $('#' + name + '_other');
  if (other && inp) { inp.classList.toggle('hidden', !other.checked); inp.required = other.checked; if (!other.checked) inp.value = ''; }
}
function readChips(name) {
  return $$(`#${name} .chip input:checked`).map(c => c.value === 'Others' ? 'Others: ' + $('#' + name + '_other').value.trim() : c.value);
}

// BRD 6.1 password policy, checked live while typing.
const RULES = [
  ['len', '8+ characters', p => p.length >= 8],
  ['upper', 'Uppercase letter (A–Z)', p => /[A-Z]/.test(p)],
  ['lower', 'Lowercase letter (a–z)', p => /[a-z]/.test(p)],
  ['special', 'Special character (! @ # $)', p => /[^A-Za-z0-9]/.test(p)],
];
function pwField(label, id, o = {}) {
  const { value = '', policy = false, match = '', full = false, autocomplete = 'new-password', placeholder = '' } = o;
  return `<div class="field ${full ? 'full' : ''}"><label for="${id}">${label}${REQ}</label><div class="pw-wrap"><input id="${id}" type="password" required autocomplete="${autocomplete}" placeholder="${esc(placeholder)}" value="${esc(value)}" ${policy ? 'data-policy' : ''} ${match ? `data-match="${match}"` : ''}><button type="button" class="pw-toggle" onclick="togglePw('${id}',this)" aria-label="Show password" aria-pressed="false">Show</button></div>${policy ? `<div class="pw-meter" data-score="0"><i></i></div><ul class="pw-rules" id="${id}_rules">${RULES.map(([k, t]) => `<li data-rule="${k}">${t}</li>`).join('')}</ul>` : ''}<small class="err" aria-live="polite"></small></div>`;
}
function togglePw(id, btn) {
  const input = $('#' + id), show = input.type === 'password';
  input.type = show ? 'text' : 'password';
  btn.textContent = show ? 'Hide' : 'Show';
  btn.setAttribute('aria-pressed', String(show));
  btn.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
}
function checkPolicy(input) {
  const p = input.value, results = RULES.map(([k, , fn]) => [k, fn(p)]);
  const list = $('#' + input.id + '_rules');
  results.forEach(([k, ok]) => list?.querySelector(`[data-rule="${k}"]`)?.classList.toggle('ok', ok));
  const score = results.filter(([, ok]) => ok).length;
  const meter = input.closest('.field').querySelector('.pw-meter');
  if (meter) meter.dataset.score = p ? score : 0;
  input.setCustomValidity(!p || score === RULES.length ? '' : 'Password must meet every rule shown above.');
  if (p) showErr(input);
}
function checkMatch(confirm) {
  const source = $('#' + confirm.dataset.match);
  const ok = !confirm.value || confirm.value === source?.value;
  confirm.setCustomValidity(ok ? '' : 'Passwords do not match.');
  const msg = confirm.closest('.field').querySelector('.err');
  if (confirm.value) {
    msg.textContent = ok ? '✓ Passwords match' : 'Passwords do not match.';
    msg.classList.toggle('good', ok);
    confirm.classList.toggle('is-invalid', !ok); confirm.classList.toggle('is-valid', ok);
  } else { msg.textContent = ''; confirm.classList.remove('is-invalid', 'is-valid'); }
}
function showErr(input) {
  const err = input.closest('.field')?.querySelector('.err');
  if (!err || input.dataset.match) return;
  const bad = !input.validity.valid;
  err.textContent = bad ? input.validationMessage : '';
  err.classList.remove('good');
  input.classList.toggle('is-invalid', bad);
  input.classList.toggle('is-valid', !bad && !!input.value && input.type !== 'checkbox');
}
function checkAltEmail() {
  const alt = $('#p_alt_email'), main = $('#p_email');
  if (!alt || !main) return;
  const same = alt.value.trim() && alt.value.trim().toLowerCase() === main.value.trim().toLowerCase();
  alt.setCustomValidity(same ? 'Alternate email must be different from the official email.' : '');
  if (alt.value) showErr(alt);
}

// One set of listeners for every form: show problems while typing, not after submitting.
document.addEventListener('input', e => {
  const t = e.target;
  if (!t.matches?.('input, select, textarea')) return;
  if (t.hasAttribute('data-policy')) { checkPolicy(t); $$(`[data-match="${t.id}"]`).forEach(c => c.value && checkMatch(c)); }
  if (t.dataset.match) checkMatch(t);
  if (t.id === 'p_email' || t.id === 'p_alt_email') checkAltEmail();
  if (t.classList.contains('touched')) showErr(t);
  if (t.closest('#loginForm')) updateLoginButton();
  if (DUP_FIELDS.includes(t.id) && state.page === 'register') {
    if (t.id === 'o_name' && !t.dataset.autofilling) delete formData.organization.place_id;  // typed by hand: no longer that Google place
    if (!formData.claim) scheduleOrgCheck();
  }
});
document.addEventListener('focusout', e => {
  const t = e.target;
  if (t.matches?.('.field input:not([type=checkbox]):not([type=file]), .field select') && t.value) { t.classList.add('touched'); showErr(t); }
});
document.addEventListener('invalid', e => { e.target.classList.add('touched'); showErr(e.target); }, true);
document.addEventListener('change', e => {
  const t = e.target, other = t.dataset?.other;
  if (other) {
    const on = t.type === 'checkbox' ? t.checked : t.value === 'Others', inp = $('#' + other);
    inp.classList.toggle('hidden', !on); inp.required = on;
    if (on) inp.focus(); else inp.value = '';
  }
  if (t.id === 'o_type') renderCategory();
  const chipField = t.closest?.('.chip-field');
  if (chipField) { syncChips(chipField.id); showErr(chipField.querySelector('.chip input')); }
});

/* ---------- Info dialogs (opened without re-rendering, so form input is kept) ---------- */
const INFO = {
  admin: ['Organization Admin responsibilities', `<p>The person who registers the organization becomes its <b>Organization Admin</b> once verification is complete. The Admin is responsible for:</p><ul><li>Keeping the organization profile accurate and updating any material change in authorization.</li><li>Inviting organization members and ending their affiliation when needed — within this organization only.</li><li>Approving or rejecting affiliation requests from SMOs (registered hospitals / sites).</li><li>For SMOs: adding hospitals / sites and inviting affiliated PIs and research teams.</li></ul><p>Organization membership never grants trial access on its own; trial access is assigned separately. Admin rights in one organization do not carry over to another.</p>`],
  terms: ['Terms and Conditions (v1.0)', `<p>The approved Terms and Conditions text will be published here before launch.</p><p>When you accept, My Trial Board records the date, time and document version (v1.0) of your acceptance.</p>`],
  privacy: ['Privacy Notice (v1.0)', `<p>The approved Privacy Notice, prepared under India's Digital Personal Data Protection Act, will be published here before launch.</p><p>Verified contact details are used for account and service-related communications only. Passwords and one-time codes are stored only in hashed form.</p>`],
  intro: ['Before you begin', `<ul class="intro-list"><li>An <b>authorized representative</b> must register the organization and will be responsible for its account administration. <button type="button" class="linkish" onclick="showInfo('admin')">What does an Organization Admin do?</button></li><li>Fields marked <span class="req">*</span> are mandatory.</li><li>You will verify your official <b>email</b> and <b>phone</b> with one-time codes. Identity verification is requested where applicable. <button type="button" class="linkish" onclick="showInfo('identity')">Details</button></li><li>Verified contact details are used for account and service-related communications.</li></ul>`, "Got it, let's start"],
  identity: ['Identity verification', `<ul><li>Only lawfully available UIDAI-authorized methods or appropriate identity verification providers will be used.</li><li>My Trial Board does not assume direct UIDAI API access.</li><li>Full Aadhaar numbers are never stored in plain text, and personal identity data is kept to a minimum.</li><li>An alternative verification method will be offered where Aadhaar is not permissible or unavailable.</li></ul><p>This version does not collect Aadhaar details.</p>`],
};
// A dialog that does not re-render the page, so form input underneath is kept. Returns { el, close }.
function openDialog(title, bodyHTML, footerHTML) {
  const el = document.createElement('div'), id = 'dlg' + Math.random().toString(36).slice(2, 8);
  el.className = 'modal-back';
  el.innerHTML = `<section class="modal" role="dialog" aria-modal="true" aria-labelledby="${id}"><div class="modal-head"><h2 id="${id}">${title}</h2><button class="btn ghost min" type="button" data-close aria-label="Close">✕</button></div><div class="dlg-body">${bodyHTML}</div>${footerHTML ? `<div class="controls">${footerHTML}</div>` : ''}</section>`;
  const close = () => { el.remove(); document.removeEventListener('keydown', onKey); };
  // Dialogs can stack (e.g. "Details" opened from the instructions); Escape closes only the top one.
  const onKey = e => { if (e.key === 'Escape' && el === [...document.querySelectorAll('.modal-back')].pop()) close(); };
  el.addEventListener('click', e => { if (e.target === el || e.target.closest('[data-close]')) close(); });
  document.addEventListener('keydown', onKey);
  document.body.append(el);
  (el.querySelector('input, textarea, .btn.primary') || el.querySelector('[data-close]')).focus();
  return { el, close };
}
function showInfo(key) {
  const [title, body, okLabel = 'Got it'] = INFO[key];
  openDialog(title, `<div class="info-body">${body}</div>`, `<span></span><button class="btn primary" type="button" data-close>${okLabel}</button>`);
}
// Small form dialog: fields HTML in, values out through onSubmit(form). onSubmit may throw to keep it open.
function formDialog(title, intro, fieldsHTML, submitLabel, onSubmit) {
  const d = openDialog(title, `${intro ? `<p class="sub">${intro}</p>` : ''}<form class="dlg-form"><div class="form-grid">${fieldsHTML}</div><div class="controls"><button type="button" class="btn ghost" data-close>Cancel</button><button class="btn primary" type="submit">${submitLabel}</button></div></form>`);
  d.el.querySelector('form').addEventListener('submit', async e => {
    e.preventDefault();
    const btn = e.target.querySelector('[type=submit]'); busy(btn, true);
    try { await onSubmit(e.target, d); } catch (err) { toast(err.message); busy(btn, false); }
  });
  return d;
}

/* ---------- Shell ---------- */
const nav = () => `<header class="nav"><a href="#" class="logo" onclick="go('home');return false"><span class="logo-mark">✳</span><span>my trial board<span style="color:var(--coral)">.</span></span></a><div class="navlinks">${state.me ? `${state.me.is_mtb_admin ? '<a href="#" onclick="openAdmin();return false">MTB Admin</a>' : ''}<a href="#" onclick="openDashboard();return false">Dashboard</a><a href="#" class="nav-keep" onclick="openProfile();return false">My Profile</a><button class="btn ghost min" onclick="logout()">Log out ↗</button>` : `<a href="#features" onclick="go('home')">How it works</a><a href="#" onclick="go('login');return false">Log in</a><button class="btn primary min" onclick="startRegistration()">Register ↗</button>`}</div></header>`;
function go(page) { state.page = page; state.modal = null; render(); window.scrollTo(0, 0); }
function startRegistration() { state.step = 0; dupResult = null; dupShownSig = ''; delete formData.claim; go('register'); showInfo('intro'); }
const PAGES = { home: () => home(), register: () => register(), verify: () => verifyPage(), created: () => createdPage(), login: () => loginPage(), recover: () => recoverPage(), dashboard: () => dashboard(), invite: () => inviteLanding(), workspace: () => workspacePage(), admin: () => adminPage() };
function render() {
  app.innerHTML = nav() + (PAGES[state.page] || home)() + `<footer class="footer">© 2026 My Trial Board · Built for trusted clinical research collaboration · Privacy &amp; security first</footer>` + (state.modal ? modalHTML() : '');
  afterRender();
}
function afterRender() {
  if (state.page === 'register' && state.step === 0) {
    renderCategory();
    MTBPlaces.attach($('#o_name'), {
      primaryTypes: () => $('#o_type').value === 'Site / Hospital / Institution' ? ['hospital', 'doctor', 'medical_lab'] : null,
      onPick: f => {
        MTBPlaces.fill({ o_name: f.name, o_address1: f.address1, o_address2: f.address2, o_city: f.city, o_state: f.state, o_country: f.country, o_pin: f.pin, o_phone: f.phone, o_website: f.website });
        formData.organization.place_id = f.placeId || '';
        toast('Address filled in from Google. Please review it.');
        runOrgCheck(true);
      },
    });
    if (!formData.claim && !dupResult && $('#o_name').value.trim()) runOrgCheck();
  }
  if (state.modal === 'hospital') attachHospitalSearch();
  if (state.modal === 'invite' && state.modalPrefill) { MTBPlaces.fill(state.modalPrefill); state.modalPrefill = null; }
  $$('[data-policy]').forEach(i => i.value && checkPolicy(i));
  $$('[data-match]').forEach(i => i.value && checkMatch(i));
  if (state.page === 'login') updateLoginButton();
  if (state.page === 'invite') loadInvite();
}

function home() { const who = ['Sponsors', 'CROs', 'SMOs', 'Research sites', 'Hospitals', 'Principal investigators', 'Coordinators', 'Institutions']; return `<main><section class="hero"><div class="three-mount" data-three="globe"></div><div class="hero-grid"></div><i class="orb o1"></i><i class="orb o2"></i><i class="orb o3"></i><div class="hero-spot"></div><div class="hero-inner"><div class="hero-copy"><div class="live-badge"><span class="pulse-dot"></span><span class="eyebrow">A more connected research ecosystem</span></div><h1><span class="w" style="--i:0">Better</span> <span class="w" style="--i:1">trials.</span><br><span class="w" style="--i:2"><span class="grad-text">Stronger</span></span> <span class="w" style="--i:3"><span class="grad-text">connections.</span></span></h1><p class="lead">Bring sponsors, CROs, research sites, SMOs and investigators together in a beautifully simple, permission-aware workspace.</p><div class="hero-actions"><button class="btn primary" onclick="startRegistration()">Register Organization ↗</button><button class="btn ghost" style="border-color:#68738a;color:white" onclick="go('login')">Access your workspace</button></div><p style="margin-top:42px;font-size:12px;color:#9faec5">ONE IDENTITY &nbsp;·&nbsp; MULTIPLE AFFILIATIONS &nbsp;·&nbsp; CONTROLLED ACCESS</p></div><div class="hero-stage" aria-hidden="true"><div class="float-chip c1"><i>✓</i>Invitation accepted</div><div class="float-chip c2"><i>✳</i>New PI affiliated</div><div class="float-chip c3"><i>⌂</i>Site affiliation approved</div><div class="stage-hint">⟲ Drag to spin</div></div></div></section><section class="marquee" aria-hidden="true"><div class="marquee-track">${who.concat(who).map(w => `<span>${w}</span>`).join('')}</div></section><section class="section" id="features"><div class="eyebrow">Designed for your workflow</div><h2>Everything begins with trust.</h2><div class="features"><div class="feature"><div class="glyph">◈</div><h3>One verified identity</h3><p>Create an organization account, verify contact channels and securely access your research workspace.</p></div><div class="feature"><div class="glyph">◎</div><h3>Smarter affiliations</h3><p>Associate hospitals, invite investigators and maintain independent organizational relationships.</p></div><div class="feature"><div class="glyph">↗</div><h3>Simple invitations</h3><p>Onboard team members and keep roles, approvals and access boundaries clearly separated.</p></div></div></section><section class="cta-band"><div class="three-mount" data-three="wave"></div><div><div class="eyebrow">Ready when you are</div><h2>Bring your research network together.</h2><p>Register once, verify your contacts and start inviting your team in minutes.</p></div><button class="btn primary" onclick="startRegistration()">Register Organization ↗</button></section></main>`; }
const authAside = (title = 'Your next trial starts here.') => `<aside class="auth-aside"><div class="three-mount" data-three="helix"></div><div class="eyebrow">MY TRIAL BOARD</div><h2>${title}</h2><p>A connected workspace for clinical research teams, with identity and affiliation controls at its foundation.</p><div class="stack"><div class="stack-row"><b>✓</b> A single, secure MTB account</div><div class="stack-row"><b>✓</b> Multiple organization workspaces</div><div class="stack-row"><b>✓</b> Approvals before institutional access</div><div class="stack-row"><b>✓</b> Traceable invitation history</div></div></aside>`;

/* ---------- Organization registration (BRD 2, 3, 6, 7) ---------- */
let formData = { organization: {}, person: {} };
function register() {
  const step = state.step;
  return `<div class="auth-layout">${authAside('Building trust from the very first step.')}<main class="auth-main"><div class="overline">Register Organization / 0${step + 1} of 03</div><h2>${['Tell us about your organization.', 'Meet the authorized representative.', 'Review and submit.'][step]}</h2><p class="sub">${['An authorized representative must register the organization. You can add team members later.', 'This representative becomes the Organization Admin after verification.', 'Confirm your authority, accept the terms and complete the security check.'][step]}</p><div class="steps">${[0, 1, 2].map(i => `<span class="step ${i <= step ? 'active' : ''}"></span>`).join('')}</div><div class="step-labels"><span>Organization</span><span>Representative</span><span>Declarations & submit</span></div><form id="registrationForm" onsubmit="nextRegistration(event)">${step === 0 ? orgFields() : step === 1 ? personFields() : reviewFields()}<div class="controls">${step ? `<button type="button" class="btn ghost" onclick="prevRegistration()">← Back</button>` : '<span></span>'}<button class="btn primary" type="submit" id="regNext">${step === 2 ? (formData.claim ? 'Submit claim & verify ↗' : 'Create & verify account ↗') : 'Continue ↗'}</button></div></form></main></div>`;
}
// The full instructions open as a pop-up when registration starts; this link reopens them.
function registrationIntro() {
  return `<button type="button" class="intro-link" onclick="showInfo('intro')"><span class="intro-icon" aria-hidden="true">i</span>View registration instructions</button>`;
}
function orgFields() {
  const o = formData.organization;
  return `${registrationIntro()}${claimBanner()}<div class="form-grid">${select('Organization type', 'o_type', OPTS.orgTypes, { required: true, full: true, value: o.type })}<div id="categoryRow" class="cat-row"></div>${field('Organization name', 'o_name', { required: true, full: true, value: o.name, placeholder: 'Start typing, e.g. Apollo Hospitals', help: state.mapsKey ? 'Pick a suggestion to fill in the address automatically.' : 'Address autofill switches on once a Google Maps key is configured.' })}<div id="dupPanel" class="full" aria-live="polite">${dupPanelHTML()}</div>${field('Acronym / short name', 'o_acronym', { value: o.acronym, placeholder: 'Optional' })}${field('Contact number', 'o_phone', { type: 'tel', value: o.phone, placeholder: '+91 40 1234 5678', attrs: PHONE })}${field('Address line 1', 'o_address1', { required: true, full: true, value: o.address1, placeholder: 'Building, street' })}${field('Address line 2', 'o_address2', { full: true, value: o.address2, placeholder: 'Area, locality (optional)' })}${field('City', 'o_city', { required: true, value: o.city })}${field('State', 'o_state', { required: true, value: o.state })}${field('Country', 'o_country', { required: true, value: o.country || 'India' })}${field('PIN / ZIP code', 'o_pin', { required: true, value: o.pin, attrs: 'pattern="[A-Za-z0-9 \\-]{3,10}" title="3–10 letters or digits"' })}${field('Website URL', 'o_website', { type: 'url', full: true, value: o.website, placeholder: 'https://' })}${docField()}</div><div class="notice">An existing organization should invite you rather than create a duplicate registration. SMOs add hospitals / sites after their account is active.</div>`;
}

/* ---------- Duplicate check, join requests and ownership claims (BRD 2, 17) ---------- */
let dupResult = null, dupTimer = null, dupSeq = 0, dupDialog = null, dupShownSig = '', dupPopTimer = null, dupTypedAt = 0;
const DUP_FIELDS = ['o_name', 'o_city', 'o_acronym', 'o_website', 'o_phone', 'o_type'];
function orgSignals() {
  const v = id => $('#' + id)?.value.trim() ?? '';
  return { type: v('o_type'), name: v('o_name'), city: v('o_city'), acronym: v('o_acronym'), website: v('o_website'), phone: v('o_phone'), place_id: formData.organization.place_id || '' };
}
function scheduleOrgCheck() { dupTypedAt = Date.now(); clearTimeout(dupTimer); dupTimer = setTimeout(runOrgCheck, 450); }
async function runOrgCheck(force = false) {
  clearTimeout(dupTimer);
  const s = orgSignals(), seq = ++dupSeq;
  if (s.name.length < 2 && !s.place_id && !s.website && !s.phone) { dupResult = null; paintDup(); return dupResult; }
  try {
    const r = await api('/org-check?' + new URLSearchParams(s));
    if (seq !== dupSeq) return dupResult;  // a newer check started while this one was running
    dupResult = r; paintDup(); maybeShowDup(force);
    return r;
  } catch { return null; }  // the server checks again on submit
}
const dupSig = () => (dupResult?.matches || []).map(m => m.id + m.level).join();
// Pop up once per new set of matches, but only after the user pauses typing, so it never interrupts a word.
function maybeShowDup(force) {
  clearTimeout(dupPopTimer);
  const sig = dupSig();
  if (dupDialog) return sig ? refreshDupDialog() : dupDialog.close();
  if (!sig || formData.claim || state.page !== 'register' || state.step !== 0) return;
  if (!force && sig === dupShownSig) return;
  const wait = 1400 - (Date.now() - dupTypedAt);
  if (!force && wait > 0) { dupPopTimer = setTimeout(() => maybeShowDup(false), wait); return; }
  showDupDialog();
}
function paintDup() { const el = $('#dupPanel'); if (el) el.innerHTML = dupPanelHTML(); }
// One-line reminder under the name field; the full details and actions live in the pop-up.
function dupPanelHTML() {
  if (formData.claim) return '';
  const ms = dupResult?.matches || [], hosp = dupResult?.hospital_record, acked = formData.organization.confirm_distinct || [];
  let html = '';
  if (ms.length) {
    const exact = ms.find(m => m.level === 'exact'), open = ms.filter(m => !acked.includes(m.id));
    const [cls, text] = exact ? ['exact', `<b>Already on My Trial Board:</b> ${esc(exact.name)}${exact.city ? ` (${esc(exact.city)})` : ''}`]
      : open.length ? ['likely', `<b>Possible match:</b> ${esc(open[0].name)}${open.length > 1 ? ` and ${open.length - 1} more` : ''}`]
      : ['done', `You confirmed this is a different organization from ${ms.length > 1 ? `${ms.length} similar records` : esc(ms[0].name)}.`];
    html += `<div class="dup-strip ${cls}"><span class="dup-strip-icon" aria-hidden="true">${cls === 'done' ? '✓' : '!'}</span><span class="dup-strip-text">${text}</span><button type="button" class="linkish" onclick="showDupDialog()">${cls === 'done' ? 'Review' : 'See options'}</button></div>`;
  }
  if (hosp) html += `<div class="soft-note dup-hospital">ⓘ An SMO has already added <b>${esc(hosp.name)}</b> (${esc(hosp.city)}) as a site. After you verify your email and phone, we'll link that record to your organization. If the SMO's details match your official email domain this is immediate; otherwise the linked SMOs have ${state.claimWindowDays || 7} days to object.</div>`;
  return html;
}
function dupDialogParts() {
  const ms = dupResult?.matches || [], acked = formData.organization.confirm_distinct || [], exact = ms.some(m => m.level === 'exact');
  const title = exact ? 'This organization is already on My Trial Board' : 'Is this your organization?';
  const body = `<p class="sub">${exact ? "It can't be registered a second time. Ask its admin to add you, or claim it if you are its authorized representative." : 'We found a similar organization. If it is yours, ask to join it instead of creating a duplicate.'}</p>${ms.map(m => {
    const pending = m.status === 'pending', isExact = m.level === 'exact';
    // For an exact match the weaker "similar name" reasons add nothing.
    const reasons = isExact ? m.reasons.filter(r => /^Same (name and city|place)/.test(r)) : m.reasons;
    return `<div class="dup-match ${isExact ? 'exact' : 'likely'}"><div class="dup-match-head"><div><b>${esc(m.name)}</b><span class="dup-meta">${esc(m.type)} · ${esc([m.city, m.state].filter(Boolean).join(', '))}</span></div><span class="dup-badge ${isExact ? 'exact' : ''}">${isExact ? 'Already registered' : 'Possible match'}</span></div><div class="dup-reasons">${reasons.map(r => `<span>${esc(r)}</span>`).join('')}</div>${pending
      ? `<p class="dup-note">A registration for this organization is waiting for email and phone verification. If it isn't completed within ${m.pending_release_hours} hours, it is released and you can register it.</p>`
      : `<div class="dup-actions"><button type="button" class="btn navy min" onclick="dupAction('join', ${m.id})">Request to join</button><button type="button" class="btn ghost min" onclick="dupAction('claim', ${m.id})">This is my organization</button></div>`}${isExact ? '' : `<label class="check dup-ack"><input type="checkbox" ${acked.includes(m.id) ? 'checked' : ''} onchange="ackDistinct(${m.id}, this.checked)"> No, mine is a different organization</label>`}</div>`;
  }).join('')}`;
  const allAcked = !exact && ms.every(m => acked.includes(m.id));
  const footer = `<span></span><button class="btn ${allAcked ? 'primary' : 'ghost'}" type="button" data-close>${exact ? 'Close' : allAcked ? 'Continue registration' : 'Close'}</button>`;
  return { title, body, footer };
}
function showDupDialog() {
  if (!dupResult?.matches?.length) return;
  dupShownSig = dupSig();
  if (dupDialog) return refreshDupDialog();
  const { title, body, footer } = dupDialogParts();
  dupDialog = openDialog(title, `<div class="dup-dialog">${body}</div>`, footer);
  dupDialog.el.querySelector('.modal').classList.add('dup-modal');
  // Forget the handle however the dialog is closed (button, ✕, Escape or backdrop).
  new MutationObserver((_, obs) => { if (!dupDialog?.el.isConnected) { dupDialog = null; obs.disconnect(); } }).observe(document.body, { childList: true });
}
function refreshDupDialog() {
  if (!dupDialog) return;
  const { title, body, footer } = dupDialogParts();
  dupDialog.el.querySelector('.modal-head h2').textContent = title;
  dupDialog.el.querySelector('.dlg-body').innerHTML = `<div class="dup-dialog">${body}</div>`;
  dupDialog.el.querySelector('.modal > .controls').innerHTML = footer;
}
function dupAction(kind, id) {
  dupDialog?.close(); dupDialog = null;
  kind === 'join' ? openJoinRequest(id) : startClaim(id);
}
function ackDistinct(id, on) {
  const s = new Set(formData.organization.confirm_distinct || []);
  on ? s.add(id) : s.delete(id);
  formData.organization.confirm_distinct = [...s];
  paintDup(); refreshDupDialog();
}
const findMatch = id => (dupResult?.matches || []).find(m => m.id === id);
function openJoinRequest(id) {
  const m = findMatch(id), p = formData.person;
  if (!m) return;
  formDialog(`Request to join ${esc(m.name)}`, `We'll pass your request to the organization's admin. Their name and email stay private. If they approve it, you'll get an invitation by email.`,
    `${field('Full name', 'j_name', { required: true, full: true, value: [p.first, p.last].filter(Boolean).join(' '), attrs: 'autocomplete="name"' })}${field('Official email', 'j_email', { type: 'email', required: true, value: p.email, placeholder: 'name@organization.org', attrs: 'autocomplete="email"' })}${field('Phone', 'j_phone', { type: 'tel', value: p.phone, placeholder: 'Optional', attrs: PHONE })}<div class="field full"><label for="j_message">Message to the admin</label><textarea id="j_message" rows="3" maxlength="500" placeholder="Optional: your role or department"></textarea></div>`,
    'Send request ↗', async (form, d) => {
      const r = await api('/join-requests', { method: 'POST', body: JSON.stringify({ org_id: id, full_name: form.j_name.value.trim(), email: form.j_email.value.trim(), phone: form.j_phone.value.trim(), message: form.j_message.value.trim() }) });
      d.el.querySelector('.dlg-body').innerHTML = `<div class="alert ok" role="status">${esc(r.message)}</div><div class="controls"><span></span><button class="btn primary" type="button" data-close>Done</button></div>`;
    });
}
// Keep what was typed on step 1 before re-rendering it (no validation here).
function saveOrgStep() {
  if (!$('#o_type')) return;
  const subtypes = OPTS.categories[$('#o_type').value] ? readChips('o_cat') : [];
  formData.organization = { ...formData.organization, ...readFields('o_', ['type', 'name', 'acronym', 'phone', 'address1', 'address2', 'city', 'state', 'country', 'pin', 'website']), subtypes };
}
let claimDialog = null;
function startClaim(id) {
  const m = findMatch(id);
  if (!m) return;
  saveOrgStep();
  const o = formData.organization;
  if (!o.type) o.type = m.type;
  if (!o.name) o.name = m.name;
  formData.claim = { org_id: m.id, name: m.name, city: m.city, type: m.type };
  render(); window.scrollTo({ top: 0, behavior: 'smooth' });
  showClaimInfo();
}
function cancelClaim() {
  claimDialog?.close(); claimDialog = null;
  saveOrgStep(); delete formData.claim; render(); runOrgCheck();
}
function showClaimInfo() {
  const cl = formData.claim;
  if (!cl) return;
  claimDialog = openDialog(`You're claiming ${esc(cl.name)}`,
    `<div class="info-body"><p>${cl.city ? `${esc(cl.name)} (${esc(cl.city)}) is already on My Trial Board. ` : ''}Fill in the form as the organization's authorized representative. No new organization is created. After you verify your email and phone, we check the claim:</p><ul class="intro-list"><li>If your official email uses the organization's website domain, you become its Organization Admin straight away.</li><li>Otherwise its current admin has ${state.claimWindowDays || 7} days to object. If nobody objects, the claim is approved.</li><li>If they object, the MTB team reviews the claim and decides.</li></ul></div>`,
    `<button type="button" class="btn ghost" onclick="cancelClaim()">Cancel claim</button><button type="button" class="btn primary" data-close>Continue as representative</button>`);
}
// One line on the page; the explanation lives in the pop-up, like the registration instructions.
function claimBanner(review = false) {
  const cl = formData.claim;
  if (!cl) return '';
  const text = review ? `<b>Ownership claim for ${esc(cl.name)}.</b> No new organization is created; the details below are kept with the claim.`
    : `<b>You're claiming</b> ${esc(cl.name)}${cl.city ? ` (${esc(cl.city)})` : ''}`;
  return `<div class="dup-strip claim claim-strip"><span class="dup-strip-icon" aria-hidden="true">⚑</span><span class="dup-strip-text">${text}</span><button type="button" class="linkish" onclick="showClaimInfo()">How it works</button>${review ? '' : `<button type="button" class="linkish" onclick="cancelClaim()">Cancel claim</button>`}</div>`;
}

function renderCategory() {
  const row = $('#categoryRow');
  if (!row) return;
  const t = $('#o_type').value, o = formData.organization;
  const saved = o.type === t ? (o.subtypes || []) : [];
  // BRD 3.1–3.2: sponsors can pick several types; a CRO or Site picks one.
  row.innerHTML = t === 'Sponsor' ? chips('Type of sponsor', 'o_cat', OPTS.categories.Sponsor, saved, { msg: 'Select at least one sponsor type.' })
    : t === 'CRO' ? chips('CRO category', 'o_cat', OPTS.categories.CRO, saved, { single: true, msg: 'Select the CRO category.' })
    : t === 'Site / Hospital / Institution' ? chips('Site / hospital type', 'o_cat', OPTS.categories[t], saved, { single: true, msg: 'Select the site / hospital type.' }) : '';
  syncChips('o_cat');
}
function readCategories() {
  const t = $('#o_type').value;
  if (!OPTS.categories[t]) return [];
  const v = readChips('o_cat');
  if (!v.length) { $('#o_cat_err').textContent = $('#o_cat').dataset.msg; $('#o_cat').scrollIntoView({ behavior: 'smooth', block: 'center' }); return false; }
  return v;
}
function docField() {
  const d = formData.organization.legal_doc;
  return `<div class="field full"><label for="o_doc">Legal / institutional document</label><label class="drop" for="o_doc"><input id="o_doc" type="file" accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg" onchange="pickDoc(this)"><span class="drop-icon" aria-hidden="true">⇪</span><span id="docName">${d ? docLabel(d) : 'Certificate of Incorporation or institutional registration document. PDF, PNG or JPG, up to 5 MB.'}</span></label><small class="help">Upload as applicable.</small><small class="err" id="docErr" aria-live="polite"></small></div>`;
}
const docLabel = d => `Attached: <b>${esc(d.name)}</b> (${Math.max(1, Math.round(d.size / 1024))} KB) <button type="button" class="linkish" onclick="removeDoc(event)">Remove</button>`;
async function pickDoc(input) {
  const f = input.files[0]; $('#docErr').textContent = '';
  if (!f) return;
  if (!/\.(pdf|png|jpe?g)$/i.test(f.name)) { input.value = ''; $('#docErr').textContent = 'Use a PDF, PNG or JPG file.'; return; }
  if (f.size > 5 * 1024 * 1024) { input.value = ''; $('#docErr').textContent = 'This file is larger than 5 MB.'; return; }
  const data = await new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(f); });
  formData.organization.legal_doc = { name: f.name, size: f.size, data };
  $('#docName').innerHTML = docLabel(formData.organization.legal_doc);
}
function removeDoc(e) { e.preventDefault(); delete formData.organization.legal_doc; $('#o_doc').value = ''; $('#docName').textContent = 'Certificate of Incorporation or institutional registration document. PDF, PNG or JPG, up to 5 MB.'; }

function personFields() {
  const p = formData.person;
  return `<div class="form-grid">${select('Salutation', 'p_salutation', OPTS.salutations, { required: true, value: p.salutation })}${select('Gender', 'p_gender', OPTS.genders, { required: true, value: p.gender })}${field('First name', 'p_first', { required: true, value: p.first, attrs: 'autocomplete="given-name"' })}${field('Middle name', 'p_middle', { value: p.middle, placeholder: 'Optional' })}${field('Last name', 'p_last', { required: true, value: p.last, attrs: 'autocomplete="family-name"' })}${field('Designation', 'p_designation', { value: p.designation, placeholder: 'e.g. Research Director' })}${field('Official email', 'p_email', { type: 'email', required: true, value: p.email, placeholder: 'name@organization.org', attrs: 'autocomplete="email"' })}${field('Alternate email', 'p_alt_email', { type: 'email', value: p.alt_email, placeholder: 'Recommended', help: 'Verified with a code and used for account recovery.' })}${field('Official contact number', 'p_phone', { type: 'tel', required: true, value: p.phone, placeholder: '+91 98765 43210', attrs: PHONE })}${field('Alternate contact number', 'p_alt_phone', { type: 'tel', value: p.alt_phone, placeholder: 'Optional', attrs: PHONE })}<div class="field full"><label>Identity verification</label><div class="soft-note">Aadhaar-based verification will be offered only through an authorized provider, with an alternative where Aadhaar is not permissible. It is <b>not collected</b> in this version. <button type="button" class="linkish" onclick="showInfo('identity')">Learn more</button></div></div>${pwField('Create password', 'p_password', { value: p.password, policy: true })}${pwField('Confirm password', 'p_confirm', { value: p.confirm, match: 'p_password' })}</div>`;
}
let captchaA = 2 + Math.floor(Math.random() * 7), captchaB = 1 + Math.floor(Math.random() * 8);
function reviewFields() {
  const o = formData.organization, p = formData.person;
  const cl = formData.claim;
  return `${claimBanner(true)}<div class="card summary"><div><div class="overline">${cl ? 'Your details for the organization' : 'Organization'}</div><h3>${esc(o.name)}</h3><p class="sub">${esc(o.type)}${o.subtypes?.length ? ' · ' + esc(o.subtypes.join(', ')) : ''}</p><p class="sub">${esc([o.address1, o.address2, o.city, o.state, o.pin, o.country].filter(Boolean).join(', '))}</p>${o.legal_doc ? `<p class="sub">Document: ${esc(o.legal_doc.name)}</p>` : ''}</div><div><div class="overline">Authorized representative</div><h3>${esc(p.salutation)} ${esc(p.first)} ${esc(p.last)}</h3><p class="sub">${esc(p.email)}${p.alt_email ? ' · alt: ' + esc(p.alt_email) : ''}</p><p class="sub">${esc(p.phone)}</p></div></div><div class="form-section"><h3>Declaration and consent</h3><label class="check"><input type="checkbox" id="authorized" required> I am authorized to register this organization on My Trial Board and to administer its account.</label><label class="check"><input type="checkbox" id="accurate" required> The information I have provided is accurate, and I will update any material change in authorization.</label><label class="check"><input type="checkbox" id="terms" required> <span>I accept the <button type="button" class="linkish" onclick="showInfo('terms')">Terms and Conditions (v1.0)</button> and acknowledge the <button type="button" class="linkish" onclick="showInfo('privacy')">Privacy Notice</button>.</span></label><div class="field" style="max-width:290px;margin-top:20px"><label for="captcha">Security check: what is ${captchaA} + ${captchaB}?${REQ}</label><input id="captcha" type="number" inputmode="numeric" required placeholder="Your answer"><small class="err"></small></div><div class="notice">Next, you will verify your email and phone${p.alt_email ? ' and alternate email' : ''} with one-time codes. The account is activated only after these checks.</div></div>`;
}
const readFields = (prefix, names) => Object.fromEntries(names.map(n => [n, $('#' + prefix + n)?.value.trim() ?? '']));
async function nextRegistration(ev) {
  ev.preventDefault();
  if (state.step === 0) {
    const subtypes = readCategories();
    if (subtypes === false) return;
    formData.organization = { ...formData.organization, ...readFields('o_', ['type', 'name', 'acronym', 'phone', 'address1', 'address2', 'city', 'state', 'country', 'pin', 'website']), subtypes };
    if (!formData.claim) {
      const btn = $('#regNext'); busy(btn, true);
      const r = await runOrgCheck(); busy(btn, false);
      const ms = r?.matches || [], acked = formData.organization.confirm_distinct || [];
      const blocked = ms.some(m => m.level === 'exact') ? 'This organization is already registered. Request to join it, or claim it if you are its authorized representative.'
        : ms.some(m => !acked.includes(m.id)) ? 'Please check the possible match below: request to join, claim it, or confirm yours is a different organization.' : '';
      if (blocked) { showDupDialog(); return; }
    }
    state.step = 1; render(); window.scrollTo(0, 0);
  } else if (state.step === 1) {
    formData.person = readFields('p_', ['salutation', 'gender', 'first', 'middle', 'last', 'designation', 'email', 'alt_email', 'phone', 'alt_phone', 'password', 'confirm']);
    state.step = 2; render(); window.scrollTo(0, 0);
  } else {
    const btn = $('#regNext'); busy(btn, true);
    try {
      const { confirm_distinct, ...organization } = formData.organization;
      const r = await api('/register', { method: 'POST', body: JSON.stringify({ organization, person: formData.person, claim_org_id: formData.claim?.org_id || null, confirm_distinct: confirm_distinct || [], authorized: $('#authorized').checked, accurate: $('#accurate').checked, terms: $('#terms').checked, captcha_expected: String(captchaA + captchaB), captcha_answer: $('#captcha').value }) });
      state.registrationId = r.registration_id; state.hasAlt = !!r.alt_email; state.claimResult = []; state.phoneCode = r.phone_code_on_screen || null;
      state.verify = { email: false, phone: false, alt_email: false };
      go('verify'); toast(r.claim ? 'Claim submitted. Verify your contact details.' : 'Registration submitted. Verify your contact details.');
    } catch (e) {
      busy(btn, false);
      // Someone registered a matching organization while this form was open: go back and show it.
      if (e.data?.matches) { dupResult = { matches: e.data.matches }; state.step = 0; render(); window.scrollTo(0, 0); showDupDialog(); }
      else toast(e.message);
    }
  }
}
function prevRegistration() {
  // Keep what was typed on the current step before going back.
  if (state.step === 1) formData.person = readFields('p_', ['salutation', 'gender', 'first', 'middle', 'last', 'designation', 'email', 'alt_email', 'phone', 'alt_phone', 'password', 'confirm']);
  state.step--; render();
}
function busy(btn, on) { if (!btn) return; btn.disabled = on; btn.classList.toggle('busy', on); }

/* ---------- Verification and account creation (BRD 8, 9) ---------- */
function otpCard(channel, icon, title, target, label) {
  const done = state.verify[channel];
  const screen = channel === 'phone' && state.phoneCode && !done
    ? `<div class="soft-note phone-screen-code">SMS isn't connected yet, so your phone code is shown here: <b>${esc(state.phoneCode)}</b></div>` : '';
  return `<div class="card otp-card ${done ? 'done' : ''}"><h3>${icon} ${title}</h3><p class="sub">${esc(target)}</p><span class="pill ${done ? 'active' : 'pending'}">${done ? 'Verified' : 'Awaiting verification'}</span>${screen}<div class="field" style="margin:17px 0"><label for="${channel}Code">${label}</label><input id="${channel}Code" maxlength="6" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" placeholder="000000" ${done ? 'disabled' : ''}></div><button class="btn navy" onclick="verifyCode('${channel}')" ${done ? 'disabled' : ''}>Verify</button> <button class="btn ghost min" onclick="resendCode('${channel}')" ${done ? 'disabled' : ''}>Resend code</button></div>`;
}
function verifyPage() {
  const p = formData.person;
  return `<div class="auth-layout">${authAside('Two checks. One trusted account.')}<div class="auth-main"><div class="overline">Submission and verification</div><h2>Almost there.</h2><p class="sub">Enter the six-digit codes we sent. Each code is valid for 15 minutes. Email codes allow 5 attempts, SMS codes allow 3.</p><div class="two-panel" style="margin:30px 0">${otpCard('email', '✉', 'Official email', p.email, '6-digit email code')}${otpCard('phone', '⌁', 'Official phone', p.phone, '6-digit SMS code')}${state.hasAlt ? otpCard('alt_email', '✉', 'Alternate email (for recovery)', p.alt_email, '6-digit email code') : ''}</div>${state.dev ? `<div class="dev"><b>Local development only:</b> open the <button class="btn ghost min" onclick="showOutbox()">OTP outbox</button> to see generated test codes. Real email and SMS delivery is not connected.</div><div id="outbox"></div>` : ''}</div></div>`;
}
async function showOutbox() { try { const r = await api('/dev/outbox'); $('#outbox').innerHTML = r.messages.slice(0, 8).map(m => `<div class="dev">${esc(m.target)}: ${esc(m.body)}</div>`).join(''); } catch (e) { toast(e.message); } }
async function verifyCode(channel) {
  try {
    const r = await api('/verify-registration', { method: 'POST', body: JSON.stringify({ registration_id: state.registrationId, channel, code: $('#' + channel + 'Code').value.trim() }) });
    state.verify[channel] = true;
    if (r.complete) { state.claimResult = r.claims || []; go('created'); }
    else { render(); toast('Verified. Please complete the remaining check' + (state.hasAlt ? 's.' : '.')); }
  } catch (e) { toast(e.message); }
}
async function resendCode(channel) {
  try {
    const r = await api('/resend-otp', { method: 'POST', body: JSON.stringify({ registration_id: state.registrationId, channel }) });
    if (r.phone_code_on_screen) { state.phoneCode = r.phone_code_on_screen; render(); }
    toast(channel === 'phone' && r.phone_code_on_screen ? 'A new phone code is shown below.' : 'A new code has been sent.');
  } catch (e) { toast(e.message); }
}
function createdPage() {
  return `<div class="auth-layout">${authAside('Welcome to My Trial Board.')}<main class="auth-main"><div class="card auth-card success-card"><div class="success-mark" aria-hidden="true"><svg viewBox="0 0 52 52"><circle cx="26" cy="26" r="24"/><path d="M15 27l7 7 15-16"/></svg></div><div class="overline">Account creation</div><h2>You're all set.</h2><p class="success-text">Your account has been created successfully. Click below to log in.</p>${(state.claimResult || []).map(c => `<div class="alert ${c.status === 'approved' ? 'ok' : 'warn'}" style="margin:0 0 18px">${claimStatusText(c)}</div>`).join('')}<button class="btn primary" style="width:100%" onclick="go('login')">Login ↗</button></div></main></div>`;
}

/* ---------- Login, lockout and unlock (BRD 10, 11.2) ---------- */
let loginCaptcha = { a: 3, b: 4 };
const newLoginCaptcha = () => { loginCaptcha = { a: 2 + Math.floor(Math.random() * 7), b: 1 + Math.floor(Math.random() * 8) }; };
function loginPage() {
  const L = state.login;
  return `<div class="auth-layout">${authAside('Welcome back to connected research.')}<div class="auth-main"><div class="card auth-card"><div class="overline">Secure sign in</div><h2>${L.locked ? 'Account locked.' : 'Your workspace awaits.'}</h2><p class="sub">${L.locked ? 'For your security, sign-in is paused after three failed attempts.' : 'Log in using your verified MTB account.'}</p>${L.message ? `<div class="alert ${L.tone}" role="alert">${esc(L.message)}</div>` : ''}${L.locked ? unlockPanel() : `<form id="loginForm" onsubmit="doLogin(event)">${field('Email / username', 'login_email', { type: 'email', required: true, value: L.email, placeholder: 'you@organization.com', attrs: 'autocomplete="username"' })}${pwField('Password', 'login_password', { autocomplete: 'current-password', placeholder: 'Your password' })}${L.failed >= 1 ? `<div class="field"><label for="login_captcha">Security check: what is ${loginCaptcha.a} + ${loginCaptcha.b}?${REQ}</label><input id="login_captcha" type="number" inputmode="numeric" required placeholder="Your answer"><small class="err"></small></div>` : ''}<div class="login-row"><a class="mutelink" style="margin-left:auto" href="#" onclick="startRecovery();return false">Forgot password?</a></div><button class="btn primary" id="loginBtn" style="width:100%" disabled>Sign in to MTB ↗</button></form><div class="switch-line">New organization? <a class="mutelink" href="#" onclick="startRegistration();return false">Register Organization</a></div>`}</div></div></div>`;
}
function updateLoginButton() {
  const btn = $('#loginBtn');
  if (!btn) return;
  const cap = $('#login_captcha');
  btn.disabled = !($('#login_email').value.trim() && $('#login_password').value && (!cap || cap.value));
}
async function doLogin(e) {
  e.preventDefault();
  const L = state.login, btn = $('#loginBtn');
  L.email = $('#login_email').value.trim();
  const body = { email: L.email, password: $('#login_password').value };
  if ($('#login_captcha')) Object.assign(body, { captcha_expected: String(loginCaptcha.a + loginCaptcha.b), captcha_answer: $('#login_captcha').value });
  busy(btn, true);
  try {
    const r = await api('/login', { method: 'POST', body: JSON.stringify(body) });
    Object.assign(L, { failed: 0, locked: false, message: '' });
    state.csrf = r.csrf; state.me = await api('/me'); state.csrf = state.me.csrf;
    if (state.inviteToken) go('invite'); else { await enterWorkspace(true); profileNudge(); }  // reminder when My Profile is not complete yet
  } catch (err) {
    if (err.status === 423) { Object.assign(L, { locked: true, tone: 'danger' }); state.unlock = null; }
    else if (err.status === 401) { L.failed++; L.tone = L.failed >= 2 ? 'danger' : 'warn'; }
    else if (err.status === 428) { L.failed = Math.max(L.failed, 1); L.tone = 'warn'; }
    else L.tone = 'warn';
    L.message = err.message;
    newLoginCaptcha(); render();
  }
}
function unlockPanel() {
  const L = state.login, U = state.unlock || (state.unlock = { step: 'email', email: L.email, error: '' });
  const err = U.error ? `<div class="alert warn" role="alert">${esc(U.error)}</div>` : '';
  if (U.step === 'code') return `<div class="unlock"><h3>Enter your unlock code</h3><p class="sub">If <b>${esc(maskEmail(U.email))}</b> belongs to a locked account, we've sent a 6-digit code to it. It expires in 15 minutes.</p>${err}<form onsubmit="event.preventDefault();unlockComplete()"><input type="hidden" id="unlock_email" value="${esc(U.email)}">${field('6-digit unlock code', 'unlock_code', { required: true, placeholder: '000000', attrs: 'maxlength="6" minlength="6" pattern="[0-9]{6}" inputmode="numeric" autocomplete="one-time-code"' })}<button class="btn primary" id="unlockBtn" style="width:100%">Verify & unlock</button>${state.dev ? `<button class="btn ghost min" style="margin-top:10px" type="button" onclick="showTestCode('unlock_email')">Show test code</button>` : ''}</form><p class="sub recover-resend">Didn't get it? <a class="mutelink" href="#" onclick="unlockRequest(true);return false">Send a new code</a></p><p class="switch-line"><a class="mutelink" href="#" onclick="state.unlock.step='email';state.unlock.error='';render();return false">Use a different email</a></p></div>`;
  if (U.step === 'done') return `<div class="success-card"><div class="success-mark" aria-hidden="true"><svg viewBox="0 0 52 52"><circle cx="26" cy="26" r="24"/><path d="M15 27l7 7 15-16"/></svg></div><h3>Account unlocked</h3><p class="success-text">You can sign in again. If you're not sure of your password, set a new one now — no second code needed.</p><button class="btn primary" style="width:100%" onclick="unlockToLogin()">Sign in</button><button class="btn ghost" style="width:100%;margin-top:10px" onclick="unlockToReset()">Reset my password</button></div>`;
  return `<div class="unlock"><h3>Unlock with a one-time code</h3><p class="sub">We'll send a code to the verified email for this account.</p>${err}<form onsubmit="event.preventDefault();unlockRequest()">${field('Registered email', 'unlock_email', { type: 'email', required: true, value: U.email })}<button class="btn navy" id="unlockBtn" style="width:100%">Send unlock code</button></form><p class="switch-line"><a class="mutelink" href="#" onclick="startRecovery();return false">Reset password instead</a> · <a class="mutelink" href="#" onclick="resetLogin();return false">Back to sign in</a></p></div>`;
}
function resetLogin() { Object.assign(state.login, { failed: 0, locked: false, message: '' }); state.unlock = null; render(); }
async function unlockRequest(resend) {
  const U = state.unlock, email = resend ? U.email : $('#unlock_email').value.trim();
  try {
    await api('/unlock/request', { method: 'POST', body: JSON.stringify({ email }) });
    if (resend) toast('If the account is locked, a new code is on its way.');
    Object.assign(U, { step: 'code', email, error: '' }); render(); $('#unlock_code')?.focus();
  } catch (e) { U.error = e.message; render(); }
}
async function unlockComplete() {
  const U = state.unlock;
  try {
    const r = await api('/unlock/complete', { method: 'POST', body: JSON.stringify({ email: U.email, code: $('#unlock_code').value.trim() }) });
    Object.assign(U, { step: 'done', token: r.reset_token, error: '' }); state.login.message = ''; render();
  } catch (e) { U.error = e.message; render(); }
}
function unlockToLogin() {
  Object.assign(state.login, { email: state.unlock.email, failed: 0, locked: false, tone: 'ok', message: 'Account unlocked. Sign in with your password.' });
  state.unlock = null; render();
}
function unlockToReset() {
  const U = state.unlock;
  state.recover = { step: 'password', email: U.email, token: U.token, error: '' };
  Object.assign(state.login, { failed: 0, locked: false, message: '' }); state.unlock = null; go('recover');
}
async function showTestCode(emailInputId) {
  const r = await api('/dev/outbox'), target = $('#' + emailInputId).value.trim().toLowerCase();
  toast(r.messages.find(m => m.target === target)?.body || 'No test code available yet.');
}

/* ---------- Password recovery (BRD 11.1) ---------- */
// One screen per step: email -> verify code -> new password -> done -> sign in.
const RECOVER_STEPS = ['Email', 'Verify', 'New password'];
state.recover = { step: 'email', email: '', token: '', error: '' };
function startRecovery() { state.recover = { step: 'email', email: state.login?.email || '', token: '', error: '' }; go('recover'); }
function maskEmail(e) { const [u, d] = String(e).split('@'); return d ? `${u.slice(0, 2)}${'•'.repeat(Math.max(1, Math.min(u.length - 2, 6)))}@${d}` : e; }
function recoverPage() {
  const R = state.recover, at = { email: 0, code: 1, password: 2 }[R.step];
  const bar = at === undefined ? '' : `<div class="steps recover-steps">${RECOVER_STEPS.map((_, i) => `<span class="step ${i <= at ? 'active' : ''}"></span>`).join('')}</div><div class="step-labels">${RECOVER_STEPS.map(s => `<span>${s}</span>`).join('')}</div>`;
  const err = R.error ? `<div class="alert warn" role="alert">${esc(R.error)}</div>` : '';
  const back = (label, to) => `<div class="switch-line"><a class="mutelink" href="#" onclick="${to};return false">${label}</a></div>`;
  let body;
  if (R.step === 'email') body = `<div class="overline">Forgot password · Step 1 of 3</div><h2>Find your account.</h2><p class="sub">Enter the official or verified alternate email for your MTB account. We'll send a 6-digit code to it.</p>${bar}${err}<form onsubmit="recoverRequest(event)">${field('Registered email', 'recover_email', { type: 'email', required: true, value: R.email, attrs: 'autocomplete="email" autofocus' })}<button class="btn primary" id="recoverBtn" style="width:100%">Send code</button></form>${back('Back to sign in', "go('login')")}`;
  else if (R.step === 'code') body = `<div class="overline">Forgot password · Step 2 of 3</div><h2>Verify it's you.</h2><p class="sub">If an account exists for <b>${esc(maskEmail(R.email))}</b>, we've sent a 6-digit code to it. The code expires in 15 minutes.</p>${bar}${err}<form onsubmit="recoverVerify(event)"><input type="hidden" id="recover_email" value="${esc(R.email)}">${field('6-digit code', 'recover_code', { required: true, placeholder: '000000', attrs: 'maxlength="6" minlength="6" pattern="[0-9]{6}" inputmode="numeric" autocomplete="one-time-code" autofocus' })}<button class="btn primary" id="recoverBtn" style="width:100%">Verify code</button>${state.dev ? `<button class="btn ghost min" style="margin-top:10px" type="button" onclick="showTestCode('recover_email')">Show test code</button>` : ''}</form><p class="sub recover-resend">Didn't get it? <a class="mutelink" href="#" onclick="recoverResend();return false">Send a new code</a></p>${back('Use a different email', "recoverTo('email')")}`;
  else if (R.step === 'password') body = `<div class="overline">Forgot password · Step 3 of 3</div><h2>Create a new password.</h2><p class="sub">Your new password must meet all the rules below.</p>${bar}${err}<form onsubmit="recoverFinish(event)">${pwField('New password', 'recover_password', { policy: true })}${pwField('Confirm new password', 'recover_confirm', { match: 'recover_password' })}<button class="btn navy" id="recoverBtn" style="width:100%">Set new password</button></form>${back('Cancel', "go('login')")}`;
  else body = `<div class="success-card"><div class="success-mark" aria-hidden="true"><svg viewBox="0 0 52 52"><circle cx="26" cy="26" r="24"/><path d="M15 27l7 7 15-16"/></svg></div><div class="overline">Password changed</div><h2>You're all set.</h2><p class="success-text">Your password has been updated. For your security, you've been signed out on all devices.</p><button class="btn primary" style="width:100%" onclick="recoverDone()">Go to sign in</button></div>`;
  return `<div class="auth-layout">${authAside('Recover your account securely.')}<div class="auth-main"><div class="card auth-card recover-card">${body}</div></div></div>`;
}
function recoverTo(step, extra = {}) { Object.assign(state.recover, { step, error: '' }, extra); render(); $('.recover-card input:not([type=hidden])')?.focus(); }
async function recoverRequest(e) {
  e.preventDefault();
  const email = $('#recover_email').value.trim(), btn = $('#recoverBtn');
  busy(btn, true);
  try { await api('/recovery/request', { method: 'POST', body: JSON.stringify({ email }) }); recoverTo('code', { email, token: '' }); }
  catch (err) { busy(btn, false); state.recover.error = err.message; render(); }
}
async function recoverResend() {
  try { await api('/recovery/request', { method: 'POST', body: JSON.stringify({ email: state.recover.email }) }); toast('If the account exists, a new code is on its way.'); }
  catch (err) { toast(err.message); }
}
async function recoverVerify(e) {
  e.preventDefault();
  const btn = $('#recoverBtn'); busy(btn, true);
  try {
    const r = await api('/recovery/verify', { method: 'POST', body: JSON.stringify({ email: state.recover.email, code: $('#recover_code').value.trim() }) });
    recoverTo('password', { token: r.reset_token });
  } catch (err) { busy(btn, false); state.recover.error = err.message; render(); }
}
async function recoverFinish(e) {
  e.preventDefault();
  const pw = $('#recover_password').value, btn = $('#recoverBtn');
  if (pw !== $('#recover_confirm').value) { state.recover.error = 'Passwords do not match.'; return render(); }
  busy(btn, true);
  try {
    await api('/recovery/complete', { method: 'POST', body: JSON.stringify({ email: state.recover.email, reset_token: state.recover.token, new_password: pw, confirm: $('#recover_confirm').value }) });
    recoverTo('done', { token: '' });
  } catch (err) {
    busy(btn, false);
    // An expired reset pass means the code has to be verified again.
    if (/expired/i.test(err.message)) recoverTo('email', { error: err.message }); else { state.recover.error = err.message; render(); }
  }
}
function recoverDone() {
  Object.assign(state.login, { email: state.recover.email, failed: 0, locked: false, tone: 'ok', message: 'Password updated. Sign in with your new password.' });
  state.recover = { step: 'email', email: '', token: '', error: '' };
  go('login');
}
async function logout() {
  try { await api('/logout', { method: 'POST', body: '{}' }); } catch {}
  state.me = null; state.csrf = ''; state.org = null; state.dash = null; rememberWorkspace(null);
  Object.assign(state.login, { failed: 0, locked: false, message: '' });
  go('login');
}

/* ---------- Dashboard ---------- */
async function loadDash() { try { state.dash = await api('/dashboard/' + state.org); state.page = 'dashboard'; render(); } catch (e) { toast(e.message); } }
function dashboard() {
  const me = state.me, d = state.dash;
  if (!me) return loginPage();
  const orgs = me.memberships, org = d?.organization, isSmo = org?.type === 'SMO';
  // People without an organization workspace (e.g. a PI linked only to SMOs) see just their own overview; admin-only tabs stay hidden from members.
  const admin = d?.role === 'Org Admin';
  const tabs = !d ? [['overview', '◫', 'My affiliations']] : [['overview', '◫', 'Overview'], admin && ['members', '♧', 'Team members'], admin && ['invitations', '✉', 'Invitations'], ['hospitals', '⌂', isSmo ? 'My Hospitals / Sites' : 'Hospitals / Sites'], ['pis', '◇', 'Affiliated PIs'], ['team', '☺', 'Team profiles'], admin && ['audit', '◴', 'Audit trail']].filter(Boolean);
  if (!tabs.some(([k]) => k === state.tab)) state.tab = 'overview';
  return `<div class="dashboard"><aside class="sidebar"><div class="side-label">Workspace</div>${tabs.map(([key, icon, label]) => `<button class="side-link ${state.tab === key ? 'selected' : ''}" onclick="setTab('${key}')"><span style="font-size:18px">${icon}</span>${label}</button>`).join('')}<div class="side-label">Account</div><button class="side-link" onclick="logout()">↪ &nbsp; Sign out</button></aside><main class="dash-body"><div class="dash-top"><div><div class="overline">${esc(org?.type || 'Your account')} workspace</div><h2>${esc(org?.name || 'Your dashboard')}</h2><p>Welcome back, ${esc(me.user.name)}. Here's what's happening.</p></div>${orgs.length ? `<select class="org-switch" aria-label="Switch workspace" onchange="changeOrg(this.value)">${orgs.map(o => `<option value="${o.org_id}" ${o.org_id == state.org ? 'selected' : ''}>${esc(o.name)} · ${esc(o.role)}${o.designation ? ' · ' + esc(o.designation) : ''}</option>`).join('')}</select>` : ''}</div>${ownershipCards()}${piAffiliationsCard()}${d ? dashboardContent() : me.pi_affiliations?.length ? '' : `<div class="card"><h3>No active workspace</h3><p>Your account is active but you do not belong to an organization yet. Accept an invitation to join one. Until then, only your personal profile is available.</p><button class="btn primary min" onclick="openProfile()">Open My Profile ↗</button></div>`}${myInvitationsCard()}</main></div>`;
}
// Invitations sent to the signed-in person's email; they can answer here without the email link.
function myInvitationsCard() {
  const list = state.me?.invitations || [];
  if (!list.length) return '';
  return `<div class="card own-card attention" style="margin-top:24px"><div class="eyebrow">Waiting for your answer</div><h3>Pending invitations for you</h3>${list.map(i => `<div class="own-row join-row"><div><div class="own-title">${esc(i.org_name)} <span class="tag">${esc(i.role)}</span></div><p class="sub">${i.kind === 'pi' ? `SMO investigator link at <b>${esc(i.hospital || 'a hospital')}</b>. This does not make you a member of the SMO.` : `Join as a member of this ${esc(i.org_type || 'organization')}.`} · sent ${fmtDate(i.created)}</p></div><div class="dup-actions"><button class="btn primary min" onclick="answerMyInvite(${i.id},'accept')">Accept</button><button class="btn ghost min" onclick="answerMyInvite(${i.id},'reject')">Decline</button></div></div>`).join('')}</div>`;
}
// A PI's SMO links belong to the person, not to an organization, so they show whatever workspace is open.
function piAffiliationsCard() {
  const list = state.me?.pi_affiliations || [];
  if (!list.length) return '';
  return `<div class="card own-card"><div class="eyebrow">My SMO affiliations</div><h3>SMOs you work with as an investigator</h3><p class="sub">One MTB account covers all of them. These links do not give trial access or imply a hospital-level agreement.</p>${list.map(a => `<div class="own-row"><div class="own-title">${esc(a.smo)} <span class="tag">${esc(a.role || 'PI')}</span> ${pill(a.status).html}</div><p class="sub">At <b>${esc(a.hospital)}</b>, ${esc([a.city, a.state].filter(Boolean).join(', '))} · since ${new Date(a.created).toLocaleDateString()}</p></div>`).join('')}</div>`;
}
function dashboardContent() {
  const d = state.dash, isAdmin = d.role === 'Org Admin', isSmo = d.organization.type === 'SMO';
  const active = d.hospitals.filter(h => h.status === 'active').length;
  const cards = `<section class="metrics"><div class="metric"><label>Team members</label><b>${d.members.length || 1}</b><small>Organization access</small></div><div class="metric"><label>Invitations</label><b>${d.invitations.length}</b><small>Sent from workspace</small></div>${isSmo || !d.smo_links?.length ? `<div class="metric"><label>Associated sites</label><b>${d.hospitals.length}</b><small>${active} active affiliations</small></div>` : `<div class="metric"><label>Affiliated SMOs</label><b>${d.smo_links.filter(s => s.status === 'active').length}</b><small>${d.smo_links.filter(s => s.status === 'pending').length} awaiting approval</small></div>`}<div class="metric"><label>Affiliated PIs</label><b>${d.pis.length}</b><small>Approved relationships</small></div></section>`;
  let content = '';
  switch (state.tab) {
    case 'overview': content = `${isAdmin ? adminRequestCards(d) : ''}<div class="two-panel"><div class="card"><div class="eyebrow">Quick actions</div><h3>Keep collaboration moving.</h3><p class="sub">Invite trusted research members and maintain access intentionally.</p><div style="display:flex;flex-wrap:wrap;gap:10px;margin-top:25px">${isAdmin ? `<button class="btn primary" onclick="openModal('invite')">+ Invite Organization Members</button>` : ''}${isSmo && isAdmin ? `<button class="btn ghost" onclick="openModal('hospital')">+ Add Hospital / Site</button><button class="btn ghost" onclick="openModal('pi')">+ Invite affiliated PI</button>` : ''}</div></div><div class="card"><div class="eyebrow">Organization status</div><h3>Profile overview</h3><p>${pill(d.organization.status).html}</p><p class="sub">${esc(d.organization.city)}, ${esc(d.organization.state)}, ${esc(d.organization.country)}</p>${d.organization.subtype ? `<p class="sub">${esc(d.organization.subtype)}</p>` : ''}<span class="tag">${esc(d.role)}</span></div></div>`; break;
    case 'members': content = (isAdmin ? adminRequestCards(d, true) : '') + table('Organization members', ['Name', 'Email', 'Role', 'Designation', 'Status', ''], d.members.map(m => [m.first + ' ' + m.last, m.email, m.role, { html: m.designation || m.department ? `${esc(m.designation || '—')}${m.department ? `<br><small class="muted">${esc(m.department)}</small>` : ''}` : '—' }, pill(m.status), isAdmin && m.id !== d.user_id && m.status === 'active' ? { html: `<button class="btn ghost min" onclick="deactivateMember(${m.membership_id})">Deactivate</button>` } : '']), isAdmin ? `<button class="btn primary min" onclick="openModal('invite')">+ Invite member</button>` : ''); break;
    case 'invitations': content = (state.devInviteLink ? devLinkBox(state.devInviteLink) : '') + table('Invitations sent', ['Invitee', 'Email', 'Type', 'Role', 'Status', ''], d.invitations.map(i => [i.full_name, i.email, i.kind === 'pi' ? `SMO PI link${i.hospital ? ' · ' + i.hospital : ''}` : 'Organization member', i.role, pill(i.status), { html: isAdmin && ['pending', 'expired'].includes(i.status) ? `<div class="row-actions"><button class="btn ghost min" onclick="resendInvite(${i.id})">Resend</button><button class="btn ghost min" onclick="cancelInvite(${i.id})">Cancel</button></div>` : '' }]), isAdmin ? `<button class="btn primary min" onclick="openModal('invite')">+ New invitation</button>` : ''); break;
    case 'hospitals':
      content = !isSmo ? (d.approvals.length || d.smo_links?.length ? '' : table('SMOs affiliated with your hospital', [], [])) : table('My Hospitals / Sites',['Hospital', 'Location', 'Type', 'Record', 'Status', ''], d.hospitals.map(h => [h.name, h.city + ', ' + h.state, h.type, h.org_id ? 'Registered' : 'Provisional', pill(h.status), { html: isAdmin && ['rejected', 'removed'].includes(h.status) ? `<button class="btn ghost min" onclick="requestHospitalAgain(${h.link_id})">Request again</button>` : isAdmin && h.can_edit ? `<button class="btn ghost min" onclick="editHospital(${h.id})">Edit site profile</button>` : '' }]), isSmo && isAdmin ? `<button class="btn primary min" onclick="openModal('hospital')">+ Add Hospital / Site</button>` : '');
      if (d.approvals.length) content += `<div class="card" style="margin-top:25px"><h3>Hospital affiliation approvals</h3>${d.approvals.map(a => `<p>${esc(a.smo)} wants to affiliate with ${esc(a.hospital)} &nbsp; <button class="btn primary min" onclick="decideHospital(${a.id},'active')">Approve</button> <button class="btn ghost min" onclick="decideHospital(${a.id},'rejected')">Reject</button></p>`).join('')}</div>`;
      if (!isSmo && d.smo_links?.length) content += `<div style="margin-top:25px">${table('SMOs affiliated with your hospital', ['SMO', 'Location', 'Hospital record', 'Affiliated PIs', 'Since', 'Status', ''], d.smo_links.map(s => [s.smo, s.city, s.hospital, String(s.pis), new Date(s.created).toLocaleDateString(), pill(s.status), { html: s.status === 'active' ? `<button class="btn ghost min" onclick="removeSmo(${s.id},'${esc(s.smo).replaceAll("'", '&#39;')}')">Remove</button>` : '' }]))}</div>`;
      break;
    case 'pis': content = !isSmo ? table('PIs working at your hospital', ['Investigator', 'Email', 'Phone', 'Designation', 'Role', 'Through SMO', 'Hospital record', 'Since', 'Status'], (d.hospital_pis || []).map(p => [p.first + ' ' + p.last, p.email, p.phone || '—', p.designation || '—', p.role || 'PI', p.smo, p.hospital, new Date(p.created).toLocaleDateString(), pill(p.status)])) : table('Affiliated investigators', ['Investigator', 'Email', 'Role', 'Hospital', 'Status'], d.pis.map(p => [p.first + ' ' + p.last, p.email, p.role || 'PI', p.hospital, pill(p.status)]), isSmo && isAdmin ? `<button class="btn primary min" onclick="openModal('pi')">+ Invite PI</button>` : ''); break;
    case 'team': content = teamTab(); break;  // profile.js
    case 'audit': content = isAdmin ? auditTrail() : `<div class="card"><h3>Audit trail</h3><p class="sub">Only this organization's admins can view its audit trail.</p></div>`; break;
  }
  return cards + content;
}

/* ---------- Organization audit trail (BRD 18) — Org Admins of any organization type ---------- */
const AUDIT_CATS = [
  ['registration', 'Registration & verification', /^(registration_|account_activated|organization_activated|invited_user_registered|duplicate_warning|ownership_claim|hospital_claim|hospital_record|mtb_admin_account)/],
  ['affiliation', 'Affiliations', /^(hospital_affiliation|pi_link|join_request)/],
  ['invitation', 'Invitations', /^invitation_/],
  ['security', 'Sign-in & security', /^(login_|logout|account_locked|account_unlocked|unlock_|recovery_|password_)/],
  ['access', 'Roles & access', /^(role_|membership_|mtb_admin_)/],
];
const AUDIT_LABELS = {
  login_success: 'Signed in', login_failed: 'Sign-in failed (wrong password)', account_locked: 'Account locked after 3 failed sign-ins', logout: 'Signed out',
  unlock_requested: 'Unlock code requested', unlock_code_failed: 'Wrong unlock code entered', account_unlocked: 'Account unlocked',
  recovery_requested: 'Password reset requested', recovery_code_verified: 'Password reset code verified', recovery_code_failed: 'Wrong password reset code entered', password_reset: 'Password changed (reset)',
  registration_submitted: 'Organization registration submitted', registration_email_verified: 'Email verified', registration_phone_verified: 'Phone verified', registration_alt_email_verified: 'Alternate email verified',
  account_activated: 'Account activated', organization_activated: 'Organization activated', invited_user_registered: 'Invited person created an account',
  invitation_sent: 'Invitation sent', invitation_resent: 'Invitation resent', invitation_cancelled: 'Invitation cancelled (revoked)', invitation_expired: 'Invitation expired', invitation_accepted: 'Invitation accepted', invitation_rejected: 'Invitation declined',
  role_granted: 'Role granted', role_revoked: 'Role revoked', membership_deactivated: 'Member deactivated (access removed)',
  hospital_affiliation_pending: 'SMO asked to affiliate with hospital', hospital_affiliation_active: 'SMO–hospital affiliation active', hospital_affiliation_rejected: 'SMO–hospital affiliation rejected', hospital_affiliation_removed: 'SMO removed from hospital',
  pi_link_created: 'SMO–PI link created', hospital_profile_updated: 'Site profile updated', hospital_duplicate_override: 'New site added despite a possible duplicate', join_requested: 'Someone asked to join', join_request_dismissed: 'Join request dismissed',
};
const auditCat = a => AUDIT_CATS.find(([, , re]) => re.test(a))?.[0] || 'other';
const auditLabel = a => AUDIT_LABELS[a] || humanAction(a);
function auditDetails(e) {
  let d = {};
  try { d = JSON.parse(e.details || '{}'); } catch {}
  const bits = [];
  if (d.to) bits.push(d.from ? `${d.from} → ${d.to}` : `→ ${d.to}`);
  if (d.changes) bits.push('Changed: ' + Object.keys(d.changes).join(', '));
  if (d.similar_to) bits.push('Similar to: ' + d.similar_to.map(x => x.name).join(', '));
  if (d.role) bits.push('Role: ' + d.role);
  if (d.designation) bits.push(d.designation);
  if (d.kind) bits.push(d.kind === 'pi' ? 'SMO–PI invitation' : 'Member invitation');
  if (d.pi) bits.push('PI: ' + d.pi);
  if (d.admin) bits.push('Admin: ' + d.admin);
  if (d.attempt) bits.push('Attempt ' + d.attempt);
  for (const k of ['via', 'reason', 'method', 'note', 'name']) if (d[k]) bits.push(String(d[k]));
  if (e.org_name && e.org_name !== state.dash?.organization?.name) bits.push('By ' + e.org_name);
  return bits.join(' · ');
}
async function loadAudit() {
  const org = state.org;
  try { const r = await api(`/organizations/${org}/audit`); state.audit = { org, rows: r.events, cat: state.audit?.cat || '', q: state.audit?.q || '' }; }
  catch (e) { state.audit = { org, rows: [], error: e.message, cat: '', q: '' }; }
  if (state.page === 'dashboard' && state.tab === 'audit') render();
}
function auditRows() {
  const A = state.audit, q = (A.q || '').toLowerCase();
  return A.rows.filter(e => (!A.cat || auditCat(e.action) === A.cat) && (!q || [auditLabel(e.action), e.actor_name, e.actor_email, e.subject_name, auditDetails(e), e.ip].join(' ').toLowerCase().includes(q)));
}
function auditTrail() {
  const A = state.audit;
  if (!A || A.org !== state.org) { loadAudit(); return `<div class="card"><p class="sub">Loading audit trail…</p></div>`; }
  if (A.error) return `<div class="card"><h3>Audit trail</h3><p class="sub">${esc(A.error)}</p></div>`;
  const rows = auditRows();
  const counts = Object.fromEntries(AUDIT_CATS.map(([k]) => [k, A.rows.filter(e => auditCat(e.action) === k).length]));
  const chips = [['', `All (${A.rows.length})`], ...AUDIT_CATS.map(([k, l]) => [k, `${l} (${counts[k]})`])].map(([k, l]) => `<button type="button" class="chip-btn ${A.cat === k ? 'on' : ''}" onclick="state.audit.cat='${k}';render()">${esc(l)}</button>`).join('');
  const filters = `<p class="sub">Registrations and verification, affiliations, invitations, sign-ins and security, and role changes for this organization and its members. Other organizations' activity is never shown.</p><div class="chip-bar">${chips}</div><form class="admin-filters" onsubmit="event.preventDefault();state.audit.q=this.q.value.trim();render()"><input name="q" aria-label="Search audit trail" placeholder="Search person, event, IP…" value="${esc(A.q || '')}"><button class="btn navy min">Search</button><button type="button" class="btn ghost min" onclick="downloadAudit()">Download CSV</button></form>`;
  return filters + table(`Audit trail (${rows.length})`, ['When', 'Who', 'Event', 'About', 'Details', 'IP / device'], rows.map(e => {
    let device = '';
    try { device = JSON.parse(e.details || '{}').device || ''; } catch {}
    return [{ html: `<span class="nowrap">${esc(fmtDate(e.created))}</span><br><small class="muted">${esc(new Date(e.created).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }))}</small>` },
      { html: e.actor_email ? `${esc(e.actor_name)}<br><small class="muted">${esc(e.actor_email)}</small>` : '<span class="muted">System</span>' },
      { html: `<b>${esc(auditLabel(e.action))}</b><br><small class="muted">${esc((AUDIT_CATS.find(([k]) => k === auditCat(e.action)) || [, 'Other'])[1])}</small>` },
      e.subject_name || (e.subject_type ? `${e.subject_type} #${e.subject_id}` : '—'), auditDetails(e) || '—',
      { html: `${esc(e.ip || '—')}${device ? `<br><small class="muted" title="${esc(device)}">${esc(device.slice(0, 32))}…</small>` : ''}` }];
  }));
}
function downloadAudit() {
  const q = v => `"${String(v ?? '').replaceAll('"', '""')}"`;
  const lines = [['When', 'Who', 'Email', 'Event', 'Category', 'About', 'Details', 'IP'].map(q).join(',')].concat(auditRows().map(e =>
    [new Date(e.created).toISOString(), e.actor_name || 'System', e.actor_email, auditLabel(e.action), auditCat(e.action), e.subject_name, auditDetails(e), e.ip].map(q).join(',')));
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/csv' }));
  a.download = `audit-trail-${(state.dash?.organization?.name || 'organization').replace(/[^a-z0-9]+/gi, '-').toLowerCase()}-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click(); URL.revokeObjectURL(a.href);
}
const pill = s => ({ html: `<span class="pill ${esc(s)}">${esc(s)}</span>` });
function table(title, headers, rows, action = '') {
  const cell = c => (c && typeof c === 'object' ? c.html : esc(c));
  return `<div class="toolbar"><h3>${esc(title)}</h3>${action}</div><div class="table-wrap">${rows.length ? `<table><thead><tr>${headers.map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(r => `<tr>${r.map(c => `<td>${cell(c)}</td>`).join('')}</tr>`).join('')}</tbody></table>` : `<div class="empty">No records yet. Use the action above to get started.</div>`}</div>`;
}
function setTab(t) { state.tab = t; if (t === 'audit') state.audit = null; render(); }
function changeOrg(id) { state.org = Number(id); state.tab = 'overview'; rememberWorkspace(state.org); loadDash(); }

/* ---------- Workspace choice after login (BRD 10.2.3) ---------- */
const WORKSPACE_KEY = 'mtb.workspace';  // per browser tab, so a refresh keeps the chosen workspace
function savedWorkspace() { try { return Number(sessionStorage.getItem(WORKSPACE_KEY)) || null; } catch { return null; } }
function rememberWorkspace(id) { try { id ? sessionStorage.setItem(WORKSPACE_KEY, String(id)) : sessionStorage.removeItem(WORKSPACE_KEY); } catch {} }
// One workspace opens straight away; several ask the user to pick. Right after login we always ask.
async function enterWorkspace(afterLogin) {
  const ms = state.me.memberships, saved = savedWorkspace();
  if (!afterLogin && ms.some(m => m.org_id === saved)) { state.org = saved; return loadDash(); }
  if (ms.length > 1) { state.org = null; state.dash = null; return go('workspace'); }
  state.org = ms[0]?.org_id || null; rememberWorkspace(state.org);
  if (state.org) await loadDash(); else if (state.me.is_mtb_admin) openAdmin('overview'); else go('dashboard');
}
function openDashboard() { if ((state.org && state.dash) || !state.me.memberships.length) go('dashboard'); else enterWorkspace(false); }

/* ---------- MTB Admin console (platform analytics, people, organizations, activity) ---------- */
state.admin = { tab: 'overview', overview: null, users: null, orgs: null, activity: null, detail: null, f: { uq: '', us: '', oq: '', ot: '', os: '', aq: '' } };
const ADMIN_TABS = [['overview', '◫', 'Overview'], ['users', '♧', 'People'], ['orgs', '⌂', 'Organizations'], ['activity', '◴', 'Activity log']];
const fmtDateTime = v => v ? new Date(v).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—';
const humanAction = a => String(a).replace(/^mtb_admin_/, 'MTB admin: ').replaceAll('_', ' ');
const adminLoading = () => `<div class="card"><p class="sub">Loading…</p></div>`;
async function openAdmin(tab) { if (tab) state.admin.tab = tab; state.admin.detail = null; state.page = 'admin'; render(); window.scrollTo(0, 0); await adminLoad(); }
function adminTab(tab) { state.admin.tab = tab; state.admin.detail = null; render(); adminLoad(); }
async function adminLoad() {
  const A = state.admin, f = A.f, qs = o => new URLSearchParams(Object.entries(o).filter(([, v]) => v)).toString();
  try {
    if (A.tab === 'overview') {
      [A.overview, A.integrity] = await Promise.all([api('/admin/overview'), api('/admin/audit-integrity')]);
      api('/admin/email-status').then(r => { A.email = r; if (state.page === 'admin' && A.tab === 'overview') render(); }).catch(() => {});  // asks Brevo, so loaded separately
    }
    if (A.tab === 'users') A.users = (await api('/admin/users?' + qs({ q: f.uq, status: f.us }))).users;
    if (A.tab === 'orgs') A.orgs = (await api('/admin/organizations?' + qs({ q: f.oq, type: f.ot, status: f.os }))).organizations;
    if (A.tab === 'activity') A.activity = (await api('/admin/activity?' + qs({ q: f.aq, limit: 300 }))).activity;
  } catch (e) { toast(e.message); }
  if (state.page === 'admin') render();
}
function adminPage() {
  const me = state.me, A = state.admin;
  if (!me) return loginPage();
  if (!me.is_mtb_admin) return `<div class="auth-main"><div class="card auth-card"><h2>MTB Admin only</h2><p class="sub">This page is for MTB Administrators.</p></div></div>`;
  const body = A.detail ? adminOrgDetail(A.detail) : { overview: adminOverview, users: adminUsers, orgs: adminOrgs, activity: adminActivity }[A.tab]();
  return `<div class="dashboard"><aside class="sidebar"><div class="side-label">MTB Admin</div>${ADMIN_TABS.map(([key, icon, label]) => `<button class="side-link ${A.tab === key ? 'selected' : ''}" onclick="adminTab('${key}')"><span style="font-size:18px">${icon}</span>${label}</button>`).join('')}<div class="side-label">Account</div><button class="side-link" onclick="openDashboard()">⇠ &nbsp; My dashboard</button><button class="side-link" onclick="logout()">↪ &nbsp; Sign out</button></aside><main class="dash-body admin-console"><div class="dash-top"><div><div class="overline">MTB Administrator</div><h2>Platform console</h2><p>Everything happening on My Trial Board. Every change you make here is recorded in the activity log.</p></div></div>${body}</main></div>`;
}
function barChart(title, sub, series) {
  const max = Math.max(1, ...series.map(p => p.count)), total = series.reduce((s, p) => s + p.count, 0);
  const day = d => new Date(d + 'T00:00:00').toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
  return `<div class="card chart-card"><div class="eyebrow">${esc(sub)}</div><h3>${esc(title)}</h3><p class="sub">${total} in total</p><div class="bars" role="img" aria-label="${esc(title)}: ${esc(series.map(p => day(p.date) + ' ' + p.count).join(', '))}"><span class="bars-max">${max}</span>${series.map(p => `<span class="bar-slot" data-tip="${esc(day(p.date))}: ${p.count}"><span class="bar" style="height:${p.count ? Math.max(3, 100 * p.count / max) : 0}%"></span></span>`).join('')}</div><div class="bars-axis"><span>${day(series[0].date)}</span><span>${day(series[series.length - 1].date)}</span></div></div>`;
}
function adminOverview() {
  const o = state.admin.overview;
  if (!o) return adminLoading();
  const rate = o.invitations.sent ? Math.round(100 * o.invitations.accepted / o.invitations.sent) : 0;
  const tiles = `<section class="metrics"><div class="metric"><label>People</label><b>${o.users.total}</b><small>${o.users.new_7d} new this week · ${o.users.pending} unverified · ${o.users.blocked} blocked</small></div><div class="metric"><label>Organizations</label><b>${o.orgs.total}</b><small>${o.orgs.active} active · ${o.orgs.pending} pending · ${o.orgs.blocked} blocked</small></div><div class="metric"><label>Invitations</label><b>${o.invitations.sent}</b><small>${rate}% accepted · ${o.invitations.pending} waiting</small></div><div class="metric"><label>Sign-ins · 7 days</label><b>${o.security.logins_7d}</b><small>${o.security.failed_7d} failed · ${o.security.locked_now} locked now</small></div></section>`;
  const maxT = Math.max(1, ...o.orgs.by_type.map(t => t.n));
  const types = `<div class="card"><div class="eyebrow">Organizations by type</div>${o.orgs.by_type.map(t => `<div class="hbar"><span>${esc(t.type)}</span><span class="hbar-track"><span class="hbar-fill" style="width:${(100 * t.n / maxT).toFixed(1)}%"></span></span><b>${t.n}</b></div>`).join('') || '<p class="sub">No organizations yet.</p>'}</div>`;
  const kv = [['Hospitals on MTB', o.links.hospitals], ['Provisional hospitals (added by SMOs)', o.links.provisional], ['Active SMO–hospital links', o.links.hospital_active], ['Waiting for hospital approval', o.links.hospital_pending], ['Active SMO–PI links', o.links.pi_active], ['Open ownership claims', o.security.open_claims]];
  const network = `<div class="card"><div class="eyebrow">Research network</div><div class="kv">${kv.map(([k, v]) => `<span>${k}</span><b>${v}</b>`).join('')}</div></div>`;
  const reviews = `<div class="two-panel" style="margin-top:18px"><div class="card"><div class="eyebrow">Needs review</div><h3>Possible duplicate people</h3><p class="sub">Accounts that share a phone number may be one person with two emails (one MTB account per person).</p>${(o.duplicate_people || []).map(g => `<div class="own-row"><div class="own-title">Phone ${esc(g.phone)} · ${g.accounts.length} accounts</div><p class="sub">${g.accounts.map(a => `${esc(a.name)} (${esc(a.email)})`).join('<br>')}</p></div>`).join('') || '<p class="sub">None found.</p>'}</div><div class="card"><div class="eyebrow">Needs review</div><h3>Possible duplicate hospitals</h3><p class="sub">An SMO said these are different hospitals although they looked similar to an existing record.</p>${(o.hospital_reviews || []).map(r => `<div class="own-row"><div class="own-title">${esc(r.hospital || r.details.name)}</div><p class="sub">Similar to ${esc((r.details.similar_to || []).map(x => x.name).join(', '))}<br>Added by ${esc(r.by_org || '')} (${esc(r.by_email || '')}) · ${fmtDate(r.created)}</p></div>`).join('') || '<p class="sub">None to review.</p>'}</div></div>`;
  const recent = `<div style="margin-top:25px">${table('Who joined recently', ['Name', 'Email', 'Organizations', 'Status', 'Joined'], o.recent_users.map(u => [u.first + ' ' + u.last, u.email, u.orgs || '—', pill(u.status), fmtDate(u.created)]))}</div>`;
  const ig = state.admin.integrity;
  const integrity = ig ? `<div class="card integrity ${ig.ok ? 'ok' : 'bad'}"><div><div class="eyebrow">Audit log protection</div><h3>${ig.ok ? 'Audit log intact' : 'Audit log has been altered'}</h3><p class="sub">${ig.ok ? `All ${ig.records} records are sealed and unchanged. Records cannot be edited or deleted, and each one is sealed to the one before it.` : `Record #${esc(ig.first_bad_id)} or one before it was changed or removed outside the app. Check the database and its backups.`}</p></div><span class="pill ${ig.ok ? 'active' : 'rejected'}">${ig.ok ? 'verified' : 'tampered'}</span></div>` : '';
  return `${tiles}${integrity}${emailCard()}<div class="two-panel">${barChart('New accounts per day', 'Last 30 days', o.signups)}${barChart('Successful sign-ins per day', 'Last 30 days', o.logins)}</div><div class="two-panel" style="margin-top:18px">${types}${network}</div>${reviews}${recent}`;
}
// Email delivery through Brevo: connected or not, today's sends against the free plan's 300 a day, and a test email.
function emailCard() {
  const e = state.admin.email;
  if (!e) return `<div class="card integrity"><div><div class="eyebrow">Email delivery</div><h3>Checking Brevo…</h3></div></div>`;
  const state_ = !e.configured ? ['Not set up', 'pending', 'Emails are not being sent yet. Codes and invitations only reach the test inbox.'] : e.ok ? [`Connected to Brevo${e.mode === 'smtp' ? ' (SMTP)' : ''}`, 'active', `Brevo account ${esc(e.account_email || '')}${e.plan ? ' · ' + esc(e.plan) : ''}.`] : ['Brevo problem', 'rejected', esc(e.error || 'Brevo did not accept the key.')];
  return `<div class="card integrity email-card ${e.configured && !e.ok ? 'bad' : ''}"><div><div class="eyebrow">Email delivery</div><h3>${state_[0]}</h3><p class="sub">${state_[2]}${e.configured ? '' : ` Add <code>BREVO_API_KEY</code>, or <code>BREVO_SMTP_LOGIN</code> and <code>BREVO_SMTP_KEY</code>, to <code>.env</code> and restart the site.`}</p><p class="sub">Sender: <b>${esc(e.sender_name)} &lt;${esc(e.sender)}&gt;</b> · Links point to ${esc(e.app_url)} · Today: ${e.sent_today} sent of ${e.daily_limit} (free plan)${e.failed_today ? ` · <b>${e.failed_today} failed</b>` : ''}</p>${e.last_error && e.failed_today ? `<p class="sub">Last error: ${esc(e.last_error.error)}</p>` : ''}</div><div class="email-actions"><span class="pill ${state_[1]}">${e.configured ? (e.ok ? 'on' : 'error') : 'off'}</span>${e.configured ? `<button class="btn ghost min" onclick="sendTestEmail(this)">Send test email</button>` : ''}</div></div>`;
}
async function sendTestEmail(btn) {
  busy(btn, true);
  try { const r = await api('/admin/test-email', { method: 'POST', body: '{}' }); toast('Test email sent to ' + r.to + '. Check the inbox (and the spam folder).'); }
  catch (e) { toast(e.message); }
  busy(btn, false); api('/admin/email-status').then(r => { state.admin.email = r; render(); }).catch(() => {});
}
const statusOptions = (opts, cur) => opts.map(([v, l]) => `<option value="${v}" ${cur === v ? 'selected' : ''}>${l}</option>`).join('');
function adminUsers() {
  const A = state.admin, list = A.users;
  const filters = `<form class="admin-filters" onsubmit="event.preventDefault();Object.assign(state.admin.f,{uq:this.q.value.trim(),us:this.s.value});adminLoad()"><input name="q" aria-label="Search people" placeholder="Search name, email or phone" value="${esc(A.f.uq)}"><select name="s" aria-label="Status">${statusOptions([['', 'All statuses'], ['active', 'Active'], ['pending', 'Unverified'], ['blocked', 'Blocked']], A.f.us)}</select><button class="btn navy min">Search</button></form>`;
  if (!list) return filters + adminLoading();
  return filters + table(`People (${list.length})`, ['Name', 'Contact', 'Organizations', 'Status', 'Joined', 'Last sign-in', ''], list.map(u => [
    { html: `<b>${esc(u.first + ' ' + u.last)}</b>${u.mtb_admin ? ' <span class="tag">MTB Admin</span>' : ''}${u.designation ? `<br><small class="muted">${esc(u.designation)}</small>` : ''}` },
    { html: `${esc(u.email)}${u.phone ? `<br><small class="muted">${esc(u.phone)}</small>` : ''}` },
    { html: (u.orgs ? esc(u.orgs) : '—') + (u.pi_links ? `<br><small class="muted">${u.pi_links} SMO–PI link${u.pi_links > 1 ? 's' : ''}</small>` : '') },
    { html: pill(u.status).html + (u.locked ? ' <span class="pill rejected">locked</span>' : '') },
    { html: `<span class="nowrap">${esc(fmtDate(u.created))}</span>` }, u.last_login ? { html: `<span class="nowrap">${esc(fmtDate(u.last_login))}</span><br><small class="muted">${esc(new Date(u.last_login).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }))}</small>` } : 'Never',
    { html: u.mtb_admin ? '' : manageMenu('adminUser', u.id, [u.locked && ['unlock', 'Unlock account'], ['signout', 'Sign out everywhere'], u.status === 'blocked' ? ['unblock', 'Unblock'] : ['block', 'Block'], ['delete', 'Delete…']]) },
  ]));
}
async function adminUser(id, action) {
  const u = state.admin.users?.find(x => x.id === id), who = u ? `${u.first} ${u.last} (${u.email})` : 'this person';
  const ask = { block: `Block ${who}?\n\nThey are signed out now and cannot sign in until you unblock them.`, delete: `Permanently delete ${who}?\n\nTheir personal details are erased and they lose all access. This cannot be undone.`, signout: `Sign ${who} out on all devices?` }[action];
  if (ask && !confirm(ask)) return;
  try {
    await api(`/admin/users/${id}/action`, { method: 'POST', body: JSON.stringify({ action }) });
    toast({ block: 'Account blocked', unblock: 'Account unblocked', unlock: 'Account unlocked', signout: 'Signed out on all devices', delete: 'Account deleted' }[action]); adminLoad();
  } catch (e) { toast(e.message); }
}
function adminOrgs() {
  const A = state.admin, list = A.orgs;
  const filters = `<form class="admin-filters" onsubmit="event.preventDefault();Object.assign(state.admin.f,{oq:this.q.value.trim(),ot:this.t.value,os:this.s.value});adminLoad()"><input name="q" aria-label="Search organizations" placeholder="Search name or city" value="${esc(A.f.oq)}"><select name="t" aria-label="Type">${statusOptions([['', 'All types'], ...OPTS_TYPES.map(t => [t, t])], A.f.ot)}</select><select name="s" aria-label="Status">${statusOptions([['', 'All statuses'], ['active', 'Active'], ['pending', 'Pending'], ['blocked', 'Blocked']], A.f.os)}</select><button class="btn navy min">Search</button></form>`;
  if (!list) return filters + adminLoading();
  return filters + table(`Organizations (${list.length})`, ['Organization', 'Type', 'Location', 'Members', 'Admins', 'Status', 'Registered', ''], list.map(o => [
    { html: `<a href="#" class="mutelink" onclick="adminOpenOrg(${o.id});return false">${esc(o.name)}</a>` }, o.type + (o.subtype ? ' · ' + o.subtype : ''), [o.city, o.state].filter(Boolean).join(', '), String(o.members), o.admins || '—', pill(o.status), fmtDate(o.created),
    { html: manageMenu('adminOrg', o.id, [['view', 'View details'], o.status === 'blocked' ? ['unblock', 'Unblock'] : ['block', 'Block'], ['delete', 'Delete…']]) },
  ]));
}
const OPTS_TYPES = ['Sponsor', 'CRO', 'SMO', 'Site / Hospital / Institution'];
const adminOrgButtons = o => `${o.status === 'blocked' ? `<button class="btn ghost min" onclick="adminOrg(${o.id},'unblock')">Unblock</button>` : `<button class="btn ghost min" onclick="adminOrg(${o.id},'block')">Block</button>`}<button class="btn ghost min danger" onclick="adminOrg(${o.id},'delete')">Delete</button>`;
async function adminOpenOrg(id) { try { state.admin.detail = await api('/admin/organizations/' + id); render(); window.scrollTo(0, 0); } catch (e) { toast(e.message); } }
// One compact "Manage…" menu per row; picking an option runs it and the menu resets.
const manageMenu = (fn, id, options) => `<select class="manage" aria-label="Manage" onchange="const v=this.value;this.value='';if(v)${fn}(${id},v)"><option value="">Manage…</option>${options.filter(Boolean).map(([v, l]) => `<option value="${v}">${l}</option>`).join('')}</select>`;
async function adminOrg(id, action) {
  if (action === 'view') return adminOpenOrg(id);
  const o = state.admin.orgs?.find(x => x.id === id) || state.admin.detail?.organization, name = o?.name || 'this organization', body = { action };
  if (action === 'block' && !confirm(`Block ${name}?\n\nIts members lose access to its workspace until you unblock it.`)) return;
  if (action === 'delete') {
    const typed = prompt(`Delete ${name}?\n\nMembers lose access, open invitations are cancelled and its SMO / hospital links end. This cannot be undone.\n\nType the organization name to confirm:`);
    if (typed === null) return;
    body.confirm_name = typed.trim();
  }
  try {
    await api(`/admin/organizations/${id}/action`, { method: 'POST', body: JSON.stringify(body) });
    toast({ block: 'Organization blocked', unblock: 'Organization unblocked', delete: 'Organization deleted' }[action]);
    if (action === 'delete') state.admin.detail = null; else if (state.admin.detail) await adminOpenOrg(id);
    adminLoad();
  } catch (e) { toast(e.message); }
}
function adminOrgDetail(d) {
  const o = d.organization, section = (title, headers, rows) => `<div style="margin-top:22px">${table(title, headers, rows)}</div>`;
  return `<button class="btn ghost min" onclick="state.admin.detail=null;render()">← Back</button><div class="card" style="margin-top:16px"><div class="eyebrow">${esc(o.type)}${o.subtype ? ' · ' + esc(o.subtype) : ''}</div><h3>${esc(o.name)} ${pill(o.status).html}</h3><p class="sub">${esc([o.address1, o.address2, o.city, o.state, o.pin, o.country].filter(Boolean).join(', '))}</p><p class="sub">${[o.phone, o.website].filter(Boolean).map(esc).join(' · ')}${o.phone || o.website ? ' · ' : ''}Registered ${fmtDate(o.created)}</p><div class="row-actions" style="justify-content:flex-start;margin-top:12px">${adminOrgButtons(o)}</div></div>`
    + section('Members', ['Name', 'Email', 'Role', 'Designation', 'Status', 'Since'], d.members.map(m => [m.first + ' ' + m.last, m.email, m.role, [m.designation, m.department].filter(Boolean).join(' · ') || '—', pill(m.status), fmtDate(m.created)]))
    + section('Invitations', ['Invitee', 'Email', 'Type', 'Role', 'Status', 'Sent'], d.invitations.map(i => [i.full_name, i.email, i.kind === 'pi' ? 'SMO PI link' : 'Member', i.role, pill(i.status), fmtDate(i.created)]))
    + section('SMO–hospital links', ['SMO', 'Hospital', 'Status', 'Since'], d.hospital_links.map(l => [l.smo, l.hospital, pill(l.status), fmtDate(l.created)]))
    + section('SMO–PI links', ['Person', 'Email', 'Role', 'SMO', 'Hospital', 'Status'], d.pis.map(p => [p.first + ' ' + p.last, p.email, p.role || 'PI', p.smo, p.hospital, pill(p.status)]))
    + section('Recent activity', ['When', 'Who', 'Action', 'IP'], d.activity.map(a => [fmtDateTime(a.created), a.actor || 'System', humanAction(a.action), a.ip || '—']));
}
function adminActivity() {
  const A = state.admin, list = A.activity;
  const filters = `<form class="admin-filters" onsubmit="event.preventDefault();state.admin.f.aq=this.q.value.trim();adminLoad()"><input name="q" aria-label="Search activity" placeholder="Search action, email or organization (e.g. login, invitation, blocked)" value="${esc(A.f.aq)}"><button class="btn navy min">Search</button></form>`;
  if (!list) return filters + adminLoading();
  return filters + table(`Activity (${list.length} most recent)`, ['When', 'Who', 'Action', 'Organization', 'Subject', 'IP / device'], list.map(a => {
    let device = '';
    try { device = JSON.parse(a.details || '{}').device || ''; } catch {}
    return [fmtDateTime(a.created), a.actor || 'System / visitor', humanAction(a.action), a.org || '—', a.subject_type ? `${a.subject_type} #${a.subject_id ?? ''}` : '—', { html: `${esc(a.ip || '—')}${device ? `<br><small class="muted" title="${esc(device)}">${esc(device.slice(0, 38))}…</small>` : ''}` }];
  }));
}
function chooseWorkspace(id) { state.org = Number(id); state.tab = 'overview'; rememberWorkspace(state.org); loadDash(); }
function workspacePage() {
  const me = state.me;
  if (!me) return loginPage();
  const links = me.pi_affiliations?.length || 0;
  return `<div class="auth-layout">${authAside('One identity. Every organization you work with.')}<div class="auth-main"><div class="card auth-card ws-card"><div class="overline">Choose a workspace</div><h2>Where would you like to work?</h2><p class="sub">You belong to ${me.memberships.length} organizations. You can switch at any time from the top of your dashboard.</p><div class="ws-list">${me.memberships.map(m => `<button type="button" class="ws-option" onclick="chooseWorkspace(${m.org_id})"><span class="ws-mark">${esc((m.name || '?').trim().charAt(0).toUpperCase())}</span><span class="ws-text"><b>${esc(m.name)}</b><small>${esc(m.type)}${m.city ? ' · ' + esc(m.city) : ''}</small>${m.designation ? `<small>${esc(m.designation)}${m.department ? ' · ' + esc(m.department) : ''}</small>` : ''}</span><span class="tag">${esc(m.role)}</span></button>`).join('')}</div>${links ? `<p class="sub ws-note">Your ${links} SMO investigator link${links > 1 ? 's' : ''} show in every workspace.</p>` : ''}</div></div></div>`;
}
function openModal(type) { state.modal = type; render(); }
function closeModal() { state.modal = null; render(); }
const devLinkBox = link => `<div class="dev"><b>Test mode:</b> emails are not sent yet, so here is the invitation link.<br><code style="overflow-wrap:anywhere">${esc(link)}</code><br><button class="btn ghost min" type="button" onclick="navigator.clipboard.writeText('${esc(link)}');toast('Copied')">Copy link</button></div>`;
async function resendInvite(id) {
  try {
    const r = await api('/invitations/' + id + '/resend', { method: 'POST', body: '{}' });
    state.devInviteLink = r.dev_invite_token ? `${location.origin}/#invite=${r.dev_invite_token}` : '';
    toast('Invitation sent again. The earlier link no longer works.'); loadDash();
  } catch (e) { toast(e.message); }
}
async function cancelInvite(id) {
  if (!confirm('Cancel this invitation? The link in the email will stop working.')) return;
  try { await api('/invitations/' + id + '/cancel', { method: 'POST', body: '{}' }); state.devInviteLink = ''; toast('Invitation cancelled'); loadDash(); } catch (e) { toast(e.message); }
}
async function answerMyInvite(id, decision) {
  try { await api('/invitations/' + id + '/respond', { method: 'POST', body: JSON.stringify({ decision }) }); toast(decision === 'accept' ? 'Invitation accepted' : 'Invitation declined'); await refreshAccount(); }
  catch (e) { toast(e.message); }
}
async function deactivateMember(id) {
  if (!confirm('Deactivate this member? They keep their MTB account and any other affiliations.')) return;
  try { await api('/memberships/' + id + '/deactivate', { method: 'POST', body: '{}' }); toast('Membership deactivated'); loadDash(); } catch (e) { toast(e.message); }
}

/* ---------- Ownership claims, disputes and join requests on the dashboard ---------- */
const fmtDate = v => new Date(typeof v === 'number' ? v * 1000 : v).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
const CLAIM_PILL = { approved: ['active', 'Approved'], objection_window: ['pending', 'Open for objections'], disputed: ['pending', 'Under MTB review'], rejected: ['rejected', 'Not approved'], awaiting_verification: ['', 'Awaiting verification'] };
function claimStatusText(c) {
  const what = c.kind === 'hospital' ? `the hospital record <b>${esc(c.target)}</b>` : `<b>${esc(c.target)}</b>`;
  switch (c.status) {
    case 'approved': return c.kind === 'hospital' ? `The hospital record ${esc(c.target)} is now linked to your organization.` : `Your claim was approved. You are now the Organization Admin of ${what}.`;
    case 'objection_window': return `Your claim for ${what} is open for objections until <b>${fmtDate(c.deadline)}</b>. If nobody objects, it is approved automatically.`;
    case 'disputed': return `Your claim for ${what} was disputed. The MTB team will review it and let you know.`;
    case 'rejected': return `Your claim for ${what} was not approved.${c.note ? ' Note: ' + esc(c.note) : ''}`;
    default: return `Your claim for ${what} starts once your email and phone are verified.`;
  }
}
function ownershipCards() {
  const me = state.me, out = [];
  const claims = (me.claims || []).filter(c => c.status !== 'approved' || Date.now() - new Date(c.created) < 14 * 864e5);
  if (claims.length) out.push(`<div class="card own-card"><div class="eyebrow">Ownership claims</div><h3>Your claims</h3>${claims.map(c => {
    const [cls, label] = CLAIM_PILL[c.status] || ['', c.status];
    return `<div class="own-row"><div class="own-title">${esc(c.target)} <span class="pill ${cls}">${label}</span></div><p class="sub">${claimStatusText(c)}</p>${c.official_phone ? `<div class="own-phone"><p class="sub">Faster: we can send a code to the official phone number Google lists for this ${c.kind === 'hospital' ? 'hospital' : 'organization'} (${esc(c.official_phone)}). Entering that code approves the claim.</p><button class="btn ghost min" onclick="claimPhoneCode(${c.id})">Send code to official phone</button></div>` : ''}</div>`;
  }).join('')}</div>`);
  if (me.is_mtb_admin && me.disputes?.length) out.push(`<div class="card own-card"><div class="eyebrow">MTB Admin</div><h3>Ownership disputes to review</h3>${me.disputes.map(c => `<div class="own-row"><div class="own-title">${esc(c.target)}${c.city ? `, ${esc(c.city)}` : ''} <span class="tag">${c.kind === 'hospital' ? 'Hospital record' : 'Organization'}</span></div><dl class="own-facts"><dt>Claimant</dt><dd>${esc(c.claimant)} · ${esc(c.claimant_email)}${c.claimant_org ? ` · for ${esc(c.claimant_org)}` : ''}</dd>${c.kind === 'organization' ? `<dt>Current admins</dt><dd>${esc(c.current_admins.join(', ') || '—')}</dd>` : ''}<dt>Website on record</dt><dd>${esc(c.target_website || '—')}</dd><dt>Objection</dt><dd>${esc(c.objection || '—')}${c.objector ? ` <span class="sub">(${esc(c.objector)})</span>` : ''}</dd><dt>Submitted</dt><dd>${fmtDate(c.created)}</dd></dl><div class="dup-actions"><button class="btn primary min" onclick="decideClaim(${c.id},'approve')">Approve claim</button><button class="btn ghost min" onclick="decideClaim(${c.id},'reject')">Reject claim</button></div></div>`).join('')}</div>`);
  return out.join('');
}
function adminRequestCards(d, joinsOnly = false) {
  let html = '';
  if (!joinsOnly && d.claims_on_org?.length) html += `<div class="card own-card attention"><div class="eyebrow">Action needed</div><h3>Ownership ${d.claims_on_org.length > 1 ? 'claims' : 'claim'} to check</h3>${d.claims_on_org.map(c => `<div class="own-row"><p>${c.kind === 'organization'
    ? `<b>${esc(c.claimant)}</b> (${esc(c.claimant_email)}) says they are the authorized representative of <b>${esc(c.target)}</b>. If the claim is approved, they become Organization Admin and your admin access ends.`
    : `<b>${esc(c.claimant_org)}</b> (${esc(c.claimant)}, ${esc(c.claimant_email)}) has claimed the hospital record <b>${esc(c.target)}</b> that your SMO works with. If approved, that organization manages the record; your affiliation stays active.`}</p><p class="sub">If this is wrong, object before <b>${fmtDate(c.deadline)}</b>. If nobody objects, the claim is approved automatically.</p><div class="dup-actions"><button class="btn primary min" onclick="objectClaim(${c.id})">Object to this claim</button></div></div>`).join('')}</div>`;
  if (d.join_requests?.length) html += `<div class="card own-card"><div class="eyebrow">Requests to join</div><h3>People asking to join ${esc(d.organization.name)}</h3>${d.join_requests.map(r => `<div class="own-row join-row"><div><div class="own-title">${esc(r.full_name)}</div><p class="sub">${esc(r.email)}${r.phone ? ' · ' + esc(r.phone) : ''} · ${fmtDate(r.created)}</p>${r.message ? `<p class="join-msg">“${esc(r.message)}”</p>` : ''}</div><div class="dup-actions"><button class="btn primary min" onclick="inviteFromRequest(${r.id})">Invite</button><button class="btn ghost min" onclick="dismissJoin(${r.id})">Dismiss</button></div></div>`).join('')}</div>`;
  return html;
}
async function refreshAccount() {
  state.me = await api('/me'); state.csrf = state.me.csrf;
  if (!state.me.memberships.some(m => m.org_id == state.org)) state.org = state.me.memberships[0]?.org_id || null;
  if (state.org) await loadDash(); else { state.dash = null; go('dashboard'); }
}
function objectClaim(id) {
  const target = state.dash?.claims_on_org?.find(c => c.id === id)?.target || 'this record';
  formDialog('Object to this claim', `Tell the MTB team why the claim for <b>${esc(target)}</b> is wrong. The claim is paused until they review it.`,
    `<div class="field full"><label for="x_reason">Reason${REQ}</label><textarea id="x_reason" rows="4" required minlength="5" maxlength="1000" placeholder="e.g. This person does not work for us."></textarea></div>`,
    'Submit objection', async (form, d) => {
      await api(`/claims/${id}/object`, { method: 'POST', body: JSON.stringify({ reason: form.x_reason.value.trim() }) });
      d.close(); toast('Objection recorded. The MTB team will review the claim.'); await refreshAccount();
    });
}
function decideClaim(id, decision) {
  const approve = decision === 'approve';
  formDialog(approve ? 'Approve this claim?' : 'Reject this claim?', approve ? 'The claimant becomes Organization Admin (or takes over the hospital record). Current admins of a claimed organization lose admin access.' : 'The claimant is told the claim was not approved. Current admins keep access.',
    `<div class="field full"><label for="x_note">Note for the record${approve ? '' : ' (shared with the claimant)'}</label><textarea id="x_note" rows="3" maxlength="500" placeholder="Optional"></textarea></div>`,
    approve ? 'Approve claim' : 'Reject claim', async (form, d) => {
      await api(`/admin/claims/${id}/decision`, { method: 'POST', body: JSON.stringify({ decision, note: form.x_note.value.trim() }) });
      d.close(); toast(approve ? 'Claim approved' : 'Claim rejected'); await refreshAccount();
    });
}
async function claimPhoneCode(id) {
  try { await api(`/claims/${id}/phone-code`, { method: 'POST', body: '{}' }); } catch (e) { return toast(e.message); }
  let dev = '';
  if (state.dev) { try { dev = (await api('/dev/outbox')).messages.find(m => m.kind === 'phone')?.body || ''; } catch {} }
  formDialog('Enter the code', `We sent a 6-digit code to the official phone number. Ask whoever answers that line for the code.${dev ? `<br><span class="dev-inline">Development only: ${esc(dev)}</span>` : ''}`,
    field('6-digit code', 'x_code', { required: true, full: true, placeholder: '000000', attrs: 'maxlength="6" inputmode="numeric" pattern="[0-9]{6}" autocomplete="one-time-code"' }),
    'Verify & approve claim', async (form, d) => {
      await api(`/claims/${id}/phone-verify`, { method: 'POST', body: JSON.stringify({ code: form.x_code.value.trim() }) });
      d.close(); toast('Claim approved'); await refreshAccount();
    });
}
function inviteFromRequest(id) {
  const r = state.dash.join_requests.find(x => x.id === id);
  if (!r) return;
  state.modalPrefill = { m_full_name: r.full_name, m_email: r.email, m_phone: r.phone };
  openModal('invite');
}
async function dismissJoin(id) {
  try { await api(`/join-requests/${id}/dismiss`, { method: 'POST', body: '{}' }); toast('Request dismissed'); loadDash(); } catch (e) { toast(e.message); }
}

/* ---------- Add hospital / invitations (BRD 4, 13, 14) ---------- */
async function editHospital(id) {
  try { state.editHospital = await api('/hospitals/' + id); openModal('hospital-edit'); } catch (e) { toast(e.message); }
}
function modalHTML() {
  const type = state.modal, org = state.dash.organization, isEdit = type === 'hospital-edit', isH = type === 'hospital' || isEdit, isPi = type === 'pi';
  const E = isEdit ? state.editHospital || {} : {};
  const title = isEdit ? 'Edit site profile' : isH ? 'Add Hospital / Site' : isPi ? 'Invite affiliated PI / team' : 'Invite Organization Members';
  const intro = isEdit ? 'Your SMO added this provisional site, so you can complete its profile. Once the hospital registers on MTB, it manages its own profile.' : isH ? 'Search first: if the hospital is already on My Trial Board you will be linked to that record. A registered hospital must approve the affiliation. Adding a hospital does not make your SMO its Hospital Admin.'
    : isPi ? 'This creates an SMO–PI relationship only. It does not grant trial access or imply a hospital-level agreement.'
    : 'Recipients join your organization through a secure, expiring invitation.';
  const activeHospitals = state.dash.hospitals.filter(h => h.status === 'active');
  const body = isH
    ? `${field('Site / hospital name', 'm_name', { required: true, full: true, value: E.name, placeholder: 'Start typing a hospital name', help: isEdit ? '' : state.mapsKey ? 'Suggestions come from MTB records and Google. Picking one fills in the details.' : 'Suggestions come from MTB records. Add a Google Maps key for address autofill.' })}<div id="m_match" class="full hidden"></div>${field('Acronym / short name', 'm_acronym', { value: E.acronym, placeholder: 'Optional' })}${select('Hospital type', 'm_type', OPTS.hospitalTypes, { required: true, other: true, value: E.type })}${field('Address line 1', 'm_address1', { required: true, full: true, value: E.address1 })}${field('Address line 2', 'm_address2', { full: true, value: E.address2, placeholder: 'Optional' })}${field('City', 'm_city', { required: true, value: E.city })}${field('State', 'm_state', { required: true, value: E.state })}${field('Country', 'm_country', { required: true, value: E.country || 'India' })}${field('PIN', 'm_pin', { required: true, value: E.pin })}${field('Contact number', 'm_phone', { type: 'tel', value: E.phone, placeholder: 'Optional', attrs: PHONE })}${field('Website URL', 'm_website', { type: 'url', value: E.website, placeholder: 'https://' })}<label class="check full"><input type="checkbox" id="m_declaration" required> I declare that these site details are accurate to the best of my knowledge, and I understand that adding this site does not make ${esc(org.name)} its Hospital Admin.</label>`
    : `${isPi ? `<div class="field full"><label for="m_hospital_id">Hospital / site${REQ}</label><select id="m_hospital_id" required><option value="">Select an associated hospital</option>${activeHospitals.map(h => `<option value="${h.id}">${esc(h.name)} · ${esc(h.city)}</option>`).join('')}</select>${activeHospitals.length ? '' : '<small class="help">Add a hospital with an active affiliation first.</small>'}</div>` : ''}${field(isPi ? 'Person name' : 'Full name', 'm_full_name', { required: true, full: true, placeholder: 'First and last name' })}${field('Email ID', 'm_email', { type: 'email', required: true, full: true, placeholder: 'invitee@hospital.org' })}${field('Phone number', 'm_phone', { type: 'tel', attrs: PHONE })}${field('Designation', 'm_designation')}${field('Department', 'm_department')}${select('Role', 'm_role', isPi ? (state.piRoles || OPTS.roles) : (state.memberRoles?.[org.type] || ['Research Team']), { required: true, other: true })}${!isPi && !isH ? '<small class="help full">Org Admin gives full admin rights for this organization, including inviting others.</small>' : ''}`;
  return `<div class="modal-back" onclick="if(event.target===this)closeModal()"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="modalTitle"><div class="modal-head"><div><div class="overline">${esc(org.name)}</div><h2 id="modalTitle">${title}</h2></div><button class="btn ghost min" onclick="closeModal()" aria-label="Close">✕</button></div><p class="sub">${intro}</p><form onsubmit="submitModal(event)"><div class="form-grid">${body}</div><div class="controls"><button type="button" class="btn ghost" onclick="closeModal()">Cancel</button><button class="btn primary" type="submit" id="modalSubmit">${isEdit ? 'Save changes' : isH ? 'Add hospital ↗' : 'Send invitation ↗'}</button></div></form><div id="modalResult"></div></section></div>`;
}
// BRD 4.3: a registered hospital gets an affiliation request; only a NEW site needs the SMO's declaration.
function setHospitalMode() {
  const pick = state.hospitalPick, linked = !!pick && $('#m_name')?.value.trim() === pick.name;
  const decl = $('#m_declaration');
  if (decl) { decl.required = !linked; decl.closest('label').classList.toggle('hidden', linked); }
  const btn = $('#modalSubmit');
  if (btn) btn.textContent = linked ? (pick.registered ? 'Send affiliation request ↗' : 'Link to this site ↗') : 'Add hospital ↗';
  if (!linked) $('#m_match')?.classList.add('hidden');
}
function attachHospitalSearch() {
  state.hospitalPick = null; state.hospitalDifferent = false;
  $('#m_name').addEventListener('input', () => { if (state.hospitalPick) setHospitalMode(); });
  MTBPlaces.attach($('#m_name'), {
    primaryTypes: ['hospital', 'doctor', 'medical_lab'],
    directory: q => api('/hospital-search?q=' + encodeURIComponent(q)).then(r => r.results.map(h => ({ label: h.name, sub: [h.city, h.state].filter(Boolean).join(', '), badge: h.registered ? 'Registered' : 'Provisional', fields: h }))),
    onPick: (f, source) => {
      state.hospitalDifferent = false;
      MTBPlaces.fill({ m_name: f.name, m_acronym: f.acronym, m_address1: f.address1, m_address2: f.address2, m_city: f.city, m_state: f.state, m_country: f.country, m_pin: f.pin, m_phone: f.phone, m_website: f.website });
      state.hospitalPlace = source === 'google' ? { id: f.placeId, name: f.name } : null;
      const note = $('#m_match');
      if (source === 'mtb') {
        const typeSel = $('#m_type');
        if (OPTS.hospitalTypes.includes(f.type)) typeSel.value = f.type;
        else if (String(f.type).startsWith('Others')) { typeSel.value = 'Others'; typeSel.dispatchEvent(new Event('change', { bubbles: true })); $('#m_type_other').value = f.type.replace(/^Others:?\s*/, ''); }
        note.innerHTML = `<div class="soft-note">✓ <b>${esc(f.name)}</b> is already on My Trial Board (${f.registered ? 'registered — its Hospital Admin must approve your request' : 'provisional record'}). You'll be linked to the existing record instead of creating a duplicate.</div>`;
        state.hospitalPick = { id: f.id, name: f.name, registered: !!f.registered };
      } else { note.innerHTML = '<div class="soft-note">Details filled in from Google. Please review them and choose the hospital type.</div>'; state.hospitalPick = null; }
      note.classList.remove('hidden');
      setHospitalMode();
    },
  });
}
async function submitModal(ev) {
  ev.preventDefault();
  const isEdit = state.modal === 'hospital-edit', isH = state.modal === 'hospital' || isEdit, isPi = state.modal === 'pi', btn = $('#modalSubmit');
  const val = id => $('#m_' + id)?.value.trim() ?? '';
  const d = { org_id: state.org };
  if (isH) { ['name', 'acronym', 'address1', 'address2', 'city', 'state', 'country', 'pin', 'phone', 'website'].forEach(k => d[k] = val(k)); d.type = readSelect('m_type'); d.declaration = $('#m_declaration').checked; d.place_id = state.hospitalPlace?.name === d.name ? state.hospitalPlace.id : '';
    if (state.hospitalPick && state.hospitalPick.name === d.name) d.hospital_id = state.hospitalPick.id;  // link to the record that was picked
    if (state.hospitalDifferent) d.different_confirmed = true; }
  else { ['full_name', 'email', 'phone', 'designation', 'department', 'hospital_id'].forEach(k => d[k] = val(k)); d.role = readSelect('m_role'); d.kind = isPi ? 'pi' : 'member'; }
  busy(btn, true);
  try {
    if (isEdit) {
      const r = await api('/hospitals/' + state.editHospital.id, { method: 'PUT', body: JSON.stringify(d) });
      toast(r.changed.length ? 'Site profile saved' : 'No changes to save'); state.modal = null; await loadDash(); return;
    }
    const r = await api(isH ? '/hospitals' : '/invitations', { method: 'POST', body: JSON.stringify(d) });
    if (!isH && r.dev_invite_token) {
      toast('Invitation created. A local test link is shown.');
      const link = `${location.origin}/#invite=${r.dev_invite_token}`;
      $('#modalResult').innerHTML = `<div class="dev"><b>Development invitation link:</b><br><code style="overflow-wrap:anywhere">${esc(link)}</code><br><button class="btn ghost min" type="button" onclick="navigator.clipboard.writeText('${esc(link)}');toast('Copied')">Copy link</button></div>`;
      state.dash = await api('/dashboard/' + state.org); busy(btn, false);
    } else {
      toast(isH ? (r.status === 'pending' ? 'Affiliation request sent to the Hospital Admin' : 'Hospital / site added') : 'Invitation sent');
      state.modal = null; await loadDash();
    }
  } catch (e) {
    busy(btn, false);
    if (e.data?.code === 'possible_duplicate') return showHospitalMatches(e.data);
    toast(e.message);
  }
}
// BRD 4.2.4: a possible duplicate is confirmed by the SMO before a second record is created.
function showHospitalMatches(data) {
  state.hospitalMatches = data.matches;
  const note = $('#m_match');
  note.innerHTML = `<div class="soft-note warn"><b>${esc(data.message)}</b>${data.matches.map((m, i) => `<div class="match-row"><div><b>${esc(m.name)}</b> <span class="tag">${m.registered ? 'Registered' : 'Provisional'}</span><br><small class="muted">${esc([m.city, m.state, m.pin].filter(Boolean).join(', '))} · ${esc(m.reasons.join('; '))}</small></div><button type="button" class="btn primary min" onclick="useHospitalMatch(${i})">Use this hospital</button></div>`).join('')}<button type="button" class="btn ghost min" style="margin-top:10px" onclick="confirmDifferentHospital()">No, it's a different hospital</button></div>`;
  note.classList.remove('hidden'); note.scrollIntoView({ block: 'nearest' });
}
function useHospitalMatch(i) {
  const m = state.hospitalMatches[i];
  MTBPlaces.fill({ m_name: m.name, m_city: m.city, m_state: m.state, m_pin: m.pin });
  state.hospitalPick = { id: m.id, name: m.name, registered: m.registered };
  $('#m_match').innerHTML = `<div class="soft-note">✓ You'll be linked to <b>${esc(m.name)}</b>${m.registered ? '. Its Hospital Admin must approve your request.' : ' (provisional record).'}</div>`;
  setHospitalMode();
}
function confirmDifferentHospital() {
  state.hospitalDifferent = true;
  $('#m_match').innerHTML = `<div class="soft-note">OK — a new site record will be created and flagged for MTB review. Tick the declaration and add the hospital.</div>`;
  $('#modalSubmit').closest('form').requestSubmit();
}
async function removeSmo(id, name) {
  if (!confirm(`Remove ${name} from this hospital? Their PIs at this hospital will lose the link. The SMO can send a new request later.`)) return;
  try { await api('/hospital-links/' + id + '/decision', { method: 'POST', body: JSON.stringify({ decision: 'removed' }) }); toast('SMO removed'); loadDash(); } catch (e) { toast(e.message); }
}
async function requestHospitalAgain(id) {
  try { const r = await api('/hospital-links/' + id + '/request-again', { method: 'POST', body: '{}' }); toast(r.status === 'pending' ? 'Request sent. The hospital admin must approve it.' : 'Hospital linked again'); loadDash(); } catch (e) { toast(e.message); }
}
async function decideHospital(id, decision) { try { await api('/hospital-links/' + id + '/decision', { method: 'POST', body: JSON.stringify({ decision }) }); toast('Affiliation updated'); loadDash(); } catch (e) { toast(e.message); } }

/* ---------- Invitation landing + invited account creation ---------- */
function inviteLanding() { return `<div class="auth-main"><div class="card auth-card" id="invitationInfo"><h2>Research invitation</h2><p>Checking invitation details...</p></div></div>`; }
async function loadInvite() {
  if (!state.inviteToken) return;
  try {
    const i = await api('/invitation/' + state.inviteToken);
    $('#invitationInfo').innerHTML = `<div class="overline">You are invited</div><h2>${esc(i.org_name)}</h2><p>${esc(i.full_name)}, you have been invited as <b>${esc(i.role)}</b>${i.kind === 'pi' ? ' (SMO–PI affiliation)' : ''}.</p><p class="sub">Invitation email: ${esc(i.email)}. To accept, sign in with this same email address.</p>${state.me ? `<button class="btn primary" onclick="respondInvite('accept')">Accept invitation</button> <button class="btn ghost" onclick="respondInvite('reject')">Decline</button>` : i.has_account ? `<p class="sub">You already have an MTB account with this email.</p><button class="btn primary" onclick="state.login.email='${esc(i.email)}';go('login')">Sign in to accept</button>` : `<p class="sub">You don't have an MTB account yet. Create one with this email to accept.</p><button class="btn primary" onclick="inviteSignup('${esc(i.email)}')">Create your account</button>`}`;
  } catch (e) { $('#invitationInfo').innerHTML = '<h2>Invitation unavailable</h2><p>' + esc(e.message) + '</p>'; }
}
function inviteSignup(invitedEmail) {
  $('#invitationInfo').innerHTML = `<div class="overline">Invitation-only onboarding</div><h2>Set up your account.</h2><p class="sub">Your email is linked to this invitation. You will verify your email and phone before joining.</p><form onsubmit="submitInvitedSignup(event)"><div class="form-grid">${select('Salutation', 'p_salutation', OPTS.salutations, { required: true })}${select('Gender', 'p_gender', OPTS.genders, { required: true })}${field('First name', 'p_first', { required: true })}${field('Last name', 'p_last', { required: true })}${field('Official email', 'p_email', { type: 'email', required: true, value: invitedEmail, full: true, attrs: 'readonly' })}${field('Phone', 'p_phone', { type: 'tel', required: true, attrs: PHONE })}${pwField('Password', 'p_password', { policy: true, full: true })}${pwField('Confirm password', 'p_confirm', { match: 'p_password', full: true })}</div><label class="check"><input type="checkbox" id="inviteTerms" required> <span>I accept the <button type="button" class="linkish" onclick="showInfo('terms')">Terms (v1.0)</button> and acknowledge the <button type="button" class="linkish" onclick="showInfo('privacy')">Privacy Notice</button>.</span></label><button class="btn primary" id="inviteSubmit">Create & verify account</button></form>`;
}
async function submitInvitedSignup(ev) {
  ev.preventDefault();
  const person = readFields('p_', ['salutation', 'gender', 'first', 'last', 'email', 'phone', 'password', 'confirm']);
  busy($('#inviteSubmit'), true);
  try {
    const r = await api('/invitation/' + state.inviteToken + '/register', { method: 'POST', body: JSON.stringify({ person, terms: $('#inviteTerms').checked }) });
    formData.person = person; state.registrationId = r.registration_id; state.hasAlt = false; state.phoneCode = r.phone_code_on_screen || null;
    state.verify = { email: false, phone: false, alt_email: false }; go('verify');
  } catch (e) { toast(e.message); busy($('#inviteSubmit'), false); }
}
async function respondInvite(decision) {
  try {
    await api('/invitation/' + state.inviteToken + '/respond', { method: 'POST', body: JSON.stringify({ decision }) });
    state.inviteToken = null; history.replaceState({}, '', location.pathname);
    state.me = await api('/me'); state.org = state.me.memberships[0]?.org_id || null;
    toast('Invitation ' + (decision === 'accept' ? 'accepted' : 'declined'));
    state.org ? await loadDash() : go('dashboard');
  } catch (e) { toast(e.message); }
}

boot();
