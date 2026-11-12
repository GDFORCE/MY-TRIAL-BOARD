/* My Profile (Module 02). Loaded after app.js and uses its helpers: $, $$, api, esc, toast, field, select, readSelect, pwField, openDialog, busy.
   The forms are drawn from /api/profile/schema, so the browser and the server always agree on fields and choices. */
state.pf = { schema: null, data: null, step: 0, review: null, search: '', team: null, person: null, nudge: '', dirty: false, poll: null, owner: null };
const PF = state.pf;
const PF_SHORT = { basic: 'Basic info', about: 'About', education: 'Education', license: 'Licenses', place_of_work: 'Place of work', trial_expertise: 'Trial expertise', tech_expertise: 'Technology', training: 'Trainings', certification: 'Certifications', publication: 'Publications', audit: 'Audits', work: 'Work experience', membership: 'Memberships', award: 'Awards', attachment: 'Attachments', declaration: 'Declaration' };
const PF_MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const pfSec = key => PF.schema.sections[key];
const pfStep = () => PF.schema.steps[PF.step];
const noOthers = s => String(s ?? '').replace(/\bOthers:\s*/g, '');
const pfBytes = n => n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB';
const pfWhen = v => v ? new Date(v).toLocaleString(undefined, { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '';
const showDate = v => { const p = String(v || '').split('-'); return p.length === 3 ? `${+p[2]} ${PF_MON[p[1] - 1]} ${p[0]}` : p.length === 2 ? `${PF_MON[p[1] - 1]} ${p[0]}` : String(v || ''); };
const pfInitials = name => String(name || '?').replace(/^(Dr|Prof|Mr|Ms|Mrs)\.\s*/, '').split(/\s+/).filter(Boolean).map(w => w[0]).slice(0, 2).join('').toUpperCase();

async function apiUpload(path, fields) {
  const fd = new FormData();
  Object.entries(fields).forEach(([k, v]) => fd.append(k, v));
  const res = await fetch('/api' + path, { method: 'POST', headers: { 'X-CSRF-Token': state.csrf }, body: fd });
  let json = {};
  try { json = await res.json(); } catch {}
  if (!res.ok) { const d = json.detail, err = Error(typeof d === 'string' ? d : d?.message || 'Upload failed'); err.status = res.status; throw err; }
  return json;
}
function confirmDialog(title, text, okLabel, onOk, danger) {
  const d = openDialog(title, `<p class="sub">${text}</p>`, `<button class="btn ghost" type="button" data-close>Cancel</button><button class="btn ${danger ? 'ghost danger' : 'primary'}" type="button" data-ok>${okLabel}</button>`);
  d.el.querySelector('[data-ok]').addEventListener('click', async e => { busy(e.target, true); try { await onOk(); d.close(); } catch (err) { toast(err.message); busy(e.target, false); } });
  return d;
}
function pfReset() { clearInterval(PF.poll); Object.assign(PF, { data: null, step: 0, review: null, search: '', team: null, person: null, nudge: '', dirty: false, poll: null, owner: null }); }
{ const baseLogout = window.logout; window.logout = async function () { pfReset(); return baseLogout(); }; }

/* ---------- Opening the page ---------- */
async function openProfile(stepKey) {
  if (!state.me) return go('login');
  try {
    if (!PF.schema) PF.schema = await api('/profile/schema');
    PF.data = await api('/profile'); PF.owner = state.me.user.id;
  } catch (e) { return toast(e.message); }
  if (stepKey) PF.step = Math.max(0, PF.schema.steps.findIndex(s => s.key === stepKey));
  PF.dirty = false; PF.search = ''; state.page = 'profile'; state.modal = null; render(); window.scrollTo(0, 0);
  if (PF.data.cv?.status === 'processing') cvWatch(PF.data.cv.id);
}
PAGES.profile = () => profilePage();
PAGES.person = () => personPage();

// The reminder after sign-in: the profile is not complete yet.
async function profileNudge() {
  PF.nudge = 'pending';
  try {
    const s = await api('/profile/summary');
    if (s.percent < 100) {
      const left = s.missing.slice(0, 6).map(m => `<li>${esc(m)}</li>`).join('') + (s.missing.length > 6 ? `<li>and ${s.missing.length - 6} more</li>` : '');
      const why = s.signed && s.changed_since && s.missing.length === 1 ? 'You changed your profile after signing the declaration. Please confirm it again.' : 'Some details are not filled in yet. A complete profile lets you export a ready CV and helps your team know your experience.';
      openDialog('Your profile is not complete yet', `<div class="pf-nudge"><div class="pf-ring" style="--p:${s.percent}"><b>${s.percent}%</b></div><div><p class="sub">${why}</p><p class="pf-nudge-label">Still to do</p><ul>${left}</ul></div></div>`,
        `<button class="btn ghost" type="button" data-close>Later</button><span class="pf-nudge-go">${s.ai ? `<button class="btn ghost" type="button" data-close onclick="openProfile().then(cvUploadDialog)">Upload CV to auto-fill</button>` : ''}<button class="btn primary" type="button" data-close onclick="openProfile()">Complete my profile ↗</button></span>`);
    }
  } catch {}
  PF.nudge = 'done';
}

/* ---------- Page shell: header, banners, step map ---------- */
function pfAvatar(cls = '') {
  const d = PF.data;
  return `<span class="pf-avatar ${cls}">${d.photo ? `<img src="/api/profile/files/${d.photo.id}" alt="">` : esc(pfInitials(d.user.name))}</span>`;
}
const pfIdHTML = () => { const d = PF.data, u = d.user; return `${pfAvatar()}<div><div class="overline">My Profile</div><h2>${esc([u.salutation, u.name].filter(Boolean).join(' '))}</h2><p class="sub">${esc([u.designation, d.basic.department].filter(Boolean).join(' · ') || 'Add your designation and department')}</p></div>`; };
const pfProgressHTML = () => { const p = PF.data.completion.percent; return `<span><b>${p}%</b> complete</span><span class="pf-bar"><i style="width:${p}%"></i></span>`; };
function pfStepsHTML() {
  const done = PF.data.completion.steps;
  return PF.schema.steps.map((s, i) => `<button type="button" class="pf-pill ${i === PF.step ? 'current' : ''} ${done[s.key] ? 'done' : ''}" onclick="pfGo(${i})" title="${esc(s.title)}"${i === PF.step ? ' aria-current="step"' : ''}><i>${done[s.key] ? '✓' : i + 1}</i>${PF_SHORT[s.key]}</button>`).join('');
}
function pfBanners() {
  const d = PF.data, cv = d.cv, out = [];
  if (cv?.status === 'processing') out.push(`<div class="pf-banner info"><span class="pf-spin"></span><div><b>Reading your CV…</b> ${esc(cv.file_name)}. This usually takes under a minute; you can keep working.</div></div>`);
  if (cv?.status === 'ready') out.push(`<div class="pf-banner ok"><div><b>Your CV has been read.</b> Review what was found. Nothing is added to your profile until you confirm it.</div><span class="pf-banner-actions"><button class="btn primary min" onclick="cvOpenReview(${cv.id})">Review now ↗</button><button class="btn ghost min" onclick="cvDiscard(${cv.id})">Discard</button></span></div>`);
  if (cv?.status === 'failed') out.push(`<div class="pf-banner warn"><div><b>Your CV could not be read.</b> ${esc(cv.error || '')}</div><span class="pf-banner-actions"><button class="btn primary min" onclick="cvUploadDialog()">Try again</button><button class="btn ghost min" onclick="cvDiscard(${cv.id},true)">Dismiss</button></span></div>`);
  if (d.declaration.signed_at && d.declaration.changed_since && pfStep().key !== 'declaration') out.push(`<div class="pf-banner warn"><div><b>Your profile changed after you signed the declaration.</b> Please confirm it again when you have finished editing.</div><span class="pf-banner-actions"><button class="btn ghost min" onclick="pfGoKey('declaration')">Go to declaration</button></span></div>`);
  return out.join('');
}
// Refresh the parts that depend on saved data without redrawing the form the person is typing in.
function pfSoft() {
  const set = (id, html) => { const el = $('#' + id); if (el) el.innerHTML = html; };
  set('pfId', pfIdHTML()); set('pfProgress', pfProgressHTML()); set('pfSteps', pfStepsHTML()); set('pfBanners', pfBanners());
  set('pfPhotoBox', pfStep().key === 'basic' ? pfPhotoHTML() : ''); set('pfLocked', pfStep().key === 'basic' ? pfLockedHTML() : '');
}
function profilePage() {
  if (!state.me) return loginPage();
  if (!PF.data || !PF.schema || PF.owner !== state.me.user.id) { openProfile(); return `<div class="pf"><div class="card"><p class="sub">Loading your profile…</p></div></div>`; }
  if (PF.review) return reviewPage();
  const steps = PF.schema.steps, s = pfStep(), n = String(PF.step + 1).padStart(2, '0');
  const body = { basic: basicStep, about: aboutStep, entries: () => entriesStep(s.key), tags: () => tagsStep(s.key), declaration: declarationStep }[s.kind]();
  const intro = s.kind === 'entries' ? pfSec(s.key).intro : s.kind === 'tags' ? PF.schema.tags[s.key].intro : { basic: 'Your details from registration are already here. Add the rest.', about: 'A short professional summary: background, years of experience, research capabilities, therapeutic expertise and notable milestones.', declaration: 'Confirm that your profile is true and accurate. This is your electronic signature.' }[s.key];
  return `<div class="pf"><div class="pf-head"><div class="pf-id" id="pfId">${pfIdHTML()}</div><div class="pf-actions"><div class="pf-progress" id="pfProgress">${pfProgressHTML()}</div><div class="pf-buttons"><button class="btn primary" id="cvUploadBtn" onclick="cvUploadDialog()">⇪ Upload CV to Auto-Fill Profile</button><button class="btn ghost" id="cvExportBtn" onclick="exportDialog()">Export Profile as CV</button></div><span class="pf-links"><button class="linkish" onclick="openPerson(state.me.user.id,'profile')">See what my team sees</button><button class="linkish" onclick="historyDialog()">Change history</button></span></div></div>
  <div id="pfBanners">${pfBanners()}</div>
  <nav class="pf-steps" id="pfSteps" aria-label="Profile sections">${pfStepsHTML()}</nav>
  <section class="card pf-card"><div class="pf-step-head"><div><div class="overline">Step ${n} of ${String(steps.length).padStart(2, '0')}</div><h3>${esc(s.title)}</h3><p class="sub">${esc(intro)}</p></div>${pfVisibility(s.key)}</div>${body}</section></div>`;
}
function pfVisibility(key) {
  if (PF.schema.shared.includes(key)) return `<label class="pf-switch" title="When on, people in your organizations can see this section. Contact details, address and files are never shown."><input type="checkbox" ${PF.data.visibility[key] ? 'checked' : ''} onchange="pfSetVisible('${key}',this)"><i></i><span>Visible to my team</span></label>`;
  return `<span class="pf-private">${key === 'basic' ? 'Your team sees your name, designation, department, research roles and photo. Contact details and address stay private.' : 'Private: only you can see this.'}</span>`;
}
async function pfSetVisible(key, box) {
  try { PF.data = await api('/profile/settings', { method: 'PUT', body: JSON.stringify({ visibility: { [key]: box.checked } }) }); toast(box.checked ? 'Your team can now see this section.' : 'This section is now hidden from your team.'); }
  catch (e) { box.checked = !box.checked; toast(e.message); }
}
async function pfSetNA(key, box) {
  try { PF.data = await api('/profile/settings', { method: 'PUT', body: JSON.stringify({ na: { [key]: box.checked } }) }); pfSoft(); }
  catch (e) { box.checked = !box.checked; toast(e.message); }
}
function pfLeaveOk() { return !PF.dirty || confirm('You have changes on this step that are not saved. Leave without saving?'); }
function pfGo(i) {
  if (i === PF.step || !pfLeaveOk()) return;
  PF.step = Math.max(0, Math.min(PF.schema.steps.length - 1, i)); PF.dirty = false; PF.search = ''; render(); window.scrollTo(0, 0);
}
const pfGoKey = key => pfGo(PF.schema.steps.findIndex(s => s.key === key));
const pfNext = () => pfGo(PF.step + 1), pfBack = () => pfGo(PF.step - 1);
function pfControls(saveLabel) {
  const last = PF.step === PF.schema.steps.length - 1;
  return `<div class="controls pf-controls">${PF.step ? `<button type="button" class="btn ghost" onclick="pfBack()">← Back</button>` : '<span></span>'}<span class="pf-controls-right">${saveLabel && !last ? `<button type="button" class="btn ghost" onclick="pfNext()">Skip</button>` : ''}${saveLabel ? `<button class="btn primary" type="submit" id="pfSave">${saveLabel}</button>` : last ? '' : `<button type="button" class="btn primary" id="pfContinue" onclick="pfNext()">Continue ↗</button>`}</span></div>`;
}
document.addEventListener('input', e => { if (e.target.closest?.('#pfForm')) PF.dirty = true; });
document.addEventListener('change', e => { if (e.target.closest?.('#pfForm')) PF.dirty = true; });
window.addEventListener('beforeunload', e => { if (state.page === 'profile' && (PF.dirty || PF.review)) { e.preventDefault(); e.returnValue = ''; } });

/* ---------- Field building blocks (driven by the schema) ---------- */
function pfChips(f, id, values = []) {
  const all = [...f.options, ...values.filter(v => !f.options.includes(v))];
  const add = f.other || f.free ? `<div class="pf-add"><input type="text" id="${id}_add" maxlength="60" placeholder="${f.free ? 'Add another' : 'Other (please specify)'}" aria-label="${esc(f.label)}: add another" onkeydown="if(event.key==='Enter'){event.preventDefault();pfAddChip('${id}',${f.free ? 0 : 1})}"><button type="button" class="btn ghost min" onclick="pfAddChip('${id}',${f.free ? 0 : 1})">Add</button></div>` : '';
  return `<fieldset class="field full pf-chipset" id="${id}"><legend>${esc(f.label)} <small class="help">Select all that apply</small></legend><div class="chip-row">${all.map(x => pfChip(x, values.includes(x))).join('')}</div>${add}</fieldset>`;
}
const pfChip = (value, on) => `<label class="chip"><input type="checkbox" value="${esc(value)}" ${on ? 'checked' : ''}><span>${esc(noOthers(value))}</span></label>`;
function pfAddChip(id, asOther) {
  const inp = $('#' + id + '_add'), text = inp.value.trim().replace(/\s+/g, ' ');
  if (text.length < 2) return inp.focus();
  const boxes = $$(`#${id} .chip input`), hit = boxes.find(b => noOthers(b.value).toLowerCase() === text.toLowerCase());
  if (hit) hit.checked = true; else $(`#${id} .chip-row`).insertAdjacentHTML('beforeend', pfChip((asOther ? 'Others: ' : '') + text, true));
  inp.value = ''; inp.focus(); if (inp.closest('#pfForm')) PF.dirty = true;
}
const pfReadChips = id => $$(`#${id} .chip input:checked`).map(i => i.value);
function pfField(f, value, p) {
  const id = p + f.key, v = value ?? '', req = f.required ? 'required' : '';
  const wrap = (inner, help = f.help, full = f.full) => `<div class="field ${full ? 'full' : ''}"><label for="${id}">${esc(f.label)}${f.required ? REQ : ''}</label>${inner}${help ? `<small class="help">${esc(help)}</small>` : ''}<small class="err" aria-live="polite"></small></div>`;
  const ph = f.placeholder ? `placeholder="${esc(f.placeholder)}"` : '';
  switch (f.type) {
    case 'select': return select(f.label, id, f.options, { required: !!f.required, other: !!f.other, value: v, help: f.help ? esc(f.help) : '', full: f.full });
    case 'multi': return pfChips(f, id, Array.isArray(v) ? v : []);
    case 'bool': return `<div class="pf-check"><label class="check"><input type="checkbox" id="${id}" ${v ? 'checked' : ''}> ${esc(f.label)}</label></div>`;
    case 'textarea': return wrap(`<textarea id="${id}" rows="4" maxlength="${f.max || 4000}" ${req} ${ph}>${esc(v)}</textarea>`, f.help, true);
    case 'combo': case 'org': return wrap(`<input id="${id}" list="${id}_dl" value="${esc(v)}" maxlength="${f.max || 200}" autocomplete="off" ${req} ${ph}><datalist id="${id}_dl">${(f.options || []).map(o => `<option value="${esc(o)}">`).join('')}</datalist>`);
    case 'date': return /^\d{4}(-\d{2})?$/.test(v)
      ? wrap(`<input id="${id}" value="${esc(v)}" pattern="\\d{4}(-\\d{2}(-\\d{2})?)?" title="Use YYYY, YYYY-MM or YYYY-MM-DD" ${req}>`, 'Only part of this date is known. Add the rest as YYYY-MM-DD if you have it.')
      : wrap(`<input id="${id}" type="date" value="${esc(v)}" min="1900-01-01" max="2099-12-31" ${req}>`);
    case 'month': return /^\d{4}$/.test(v)
      ? wrap(`<input id="${id}" value="${esc(v)}" pattern="\\d{4}(-\\d{2})?" title="Use YYYY or YYYY-MM" ${req}>`, 'Only the year is known. Add the month as YYYY-MM if you have it.')
      : wrap(`<input id="${id}" type="month" value="${esc(v)}" pattern="\\d{4}-\\d{2}" placeholder="YYYY-MM" ${req}>`);
    case 'year': return wrap(`<input id="${id}" value="${esc(v)}" inputmode="numeric" maxlength="4" pattern="(19|20)\\d{2}" title="Four-digit year" placeholder="YYYY" ${req}>`);
    case 'url': return wrap(`<input id="${id}" type="url" value="${esc(v)}" maxlength="500" ${req} ${ph}>`);
    default: return wrap(`<input id="${id}" value="${esc(v)}" maxlength="${f.max || 200}" ${req} ${ph}>`);
  }
}
function pfRead(f, p) {
  const id = p + f.key, el = $('#' + id);
  if (f.type === 'multi') return pfReadChips(id);
  if (!el) return undefined;
  return f.type === 'bool' ? el.checked : f.type === 'select' ? readSelect(id) : el.value.trim();
}

/* ---------- Step 1: Basic information ---------- */
function pfPhotoHTML() {
  const d = PF.data, tile = m => `<div class="pf-thumb">${m.mime.startsWith('video') ? `<video src="/api/profile/files/${m.id}" preload="metadata" muted></video><span class="pf-play">▶</span>` : `<img src="/api/profile/files/${m.id}" alt="${esc(m.name)}" loading="lazy">`}<a class="pf-thumb-open" href="/api/profile/files/${m.id}" target="_blank" rel="noopener" aria-label="Open ${esc(m.name)}"></a><button type="button" class="pf-thumb-x" onclick="pfRemoveFile('${m.id}')" aria-label="Remove ${esc(m.name)}">✕</button></div>`;
  return `<div class="pf-photo">${pfAvatar('large')}<div><b>Profile picture</b><p class="sub">Optional. ${esc(PF.schema.file_rules.photo.replace(/^a /, ''))}.</p><div class="pf-inline"><label class="btn ghost min pf-filebtn">${d.photo ? 'Change photo' : 'Upload photo'}<input type="file" id="pfPhotoInput" accept="image/png,image/jpeg,image/webp" onchange="pfUploadMedia(this,'photo')"></label>${d.photo ? `<button type="button" class="btn ghost min" onclick="pfRemoveFile('${d.photo.id}')">Remove</button>` : ''}</div></div></div>
  <div class="pf-gallery"><b>Photos / videos</b> <span class="sub">Optional, up to ${PF.schema.media_limit}. Only you can see them for now.</span><div class="pf-thumbs">${d.media.map(tile).join('')}${d.media.length < PF.schema.media_limit ? `<label class="pf-thumb add" title="${esc(PF.schema.file_rules.media)}"><input type="file" id="pfMediaInput" accept="image/png,image/jpeg,image/webp,video/mp4,video/webm" onchange="pfUploadMedia(this,'media')"><span>＋<small>Add</small></span></label>` : ''}</div></div>`;
}
async function pfUploadMedia(input, kind) {
  const file = input.files[0]; if (!file) return;
  const label = input.closest('label'); label.classList.add('busy');
  try { await apiUpload('/profile/files', { kind, file }); PF.data = await api('/profile'); pfSoft(); toast(kind === 'photo' ? 'Profile picture updated.' : 'Added.'); }
  catch (e) { toast(e.message); label.classList.remove('busy'); input.value = ''; }
}
async function pfRemoveFile(id) {
  try { PF.data = await api('/profile/files/' + id, { method: 'DELETE', body: '{}' }); pfSoft(); } catch (e) { toast(e.message); }
}
function pfLockedHTML() {
  const d = PF.data, u = d.user, pend = d.pending_contact;
  const ok = '<span class="pill active">Verified</span>', no = '<span class="pill pending">Not verified</span>';
  const row = (label, value, badge, actions) => `<div class="pf-lock"><span class="pf-lock-label">${label}</span><span class="pf-lock-value">${value} ${badge || ''}</span><span class="pf-lock-actions">${actions || ''}</span></div>`;
  const btn = (text, call) => `<button type="button" class="linkish" onclick="${call}">${text}</button>`;
  const waiting = ch => pend[ch] ? `<br><small class="muted">Waiting for the code sent to ${esc(pend[ch])}. ${btn('Enter code', `contactCodeDialog('${ch}')`)}</small>` : '';
  return row('Name', esc([u.first, u.middle, u.last].filter(Boolean).join(' ')), '', btn('Change name', 'nameDialog()'))
    + row('Primary email ID', esc(u.email) + waiting('email'), ok, btn('Change', "contactDialog('email')"))
    + row('Primary phone number', esc(u.phone) + waiting('phone'), ok, btn('Change', "contactDialog('phone')"))
    + row('Alternate email ID', (u.alt_email ? esc(u.alt_email) : '<span class="muted">Not added</span>') + waiting('alt_email'), u.alt_email ? (u.alt_email_verified ? ok : no) : '',
      u.alt_email ? `${u.alt_email_verified ? '' : btn('Verify', "contactDialog('alt_email',true)") + ' · '}${btn('Change', "contactDialog('alt_email')")} · ${btn('Remove', 'removeAltEmail()')}` : btn('Add', "contactDialog('alt_email')"))
    + row('User role', d.roles.length ? d.roles.map(r => `<span class="tag">${esc(r.role)} · ${esc(r.org)}</span>`).join(' ') : '<span class="muted">No organization yet</span>', '', '<small class="muted">Set by each organization</small>');
}
function basicStep() {
  const d = PF.data, u = d.user, b = d.basic, S = PF.schema.basic;
  const f = (key, extra = {}) => pfField({ ...S[key], ...extra }, key in b ? b[key] : u[key], 'b_');
  const all = { ...u, ...b }, open = PF.schema.needed.filter(k => !(Array.isArray(all[k]) ? all[k].length : all[k])).map(k => S[k].label);
  return `${open.length ? `<div class="soft-note pf-note pf-needed">To complete this step, please fill in: <b>${open.map(esc).join(', ')}</b>.</div>` : ''}<div class="pf-block" id="pfPhotoBox">${pfPhotoHTML()}</div>
  <div class="pf-block"><h4>Verified details</h4><p class="sub">These came from your registration. Changing them needs your password, and a code for email or phone.</p><div class="pf-locked" id="pfLocked">${pfLockedHTML()}</div></div>
  <form id="pfForm" onsubmit="saveBasic(event)" novalidate><div class="pf-block"><h4>Personal and professional details</h4><div class="form-grid">${f('salutation', { required: true })}${f('gender', { required: true })}${f('designation')}${f('department')}${f('research_roles')}${f('languages')}</div></div>
  <div class="pf-block"><h4>Other contact and address</h4><div class="form-grid">${f('alt_phone', { placeholder: 'Optional' })}${f('landline', { placeholder: 'Optional' })}${f('address1', { full: true })}${f('address2')}${f('address3')}${f('country')}${f('state')}${f('city')}${f('pin')}</div><p class="soft-note pf-note">Identity documents such as Aadhaar are not collected in this version. They will never appear on your profile or in your CV.</p></div>${pfControls('Save & continue ↗')}</form>`;
}
function pfValidate(form) {
  if (form.checkValidity()) return true;
  const bad = form.querySelector(':invalid'); form.querySelectorAll(':invalid').forEach(i => { i.classList.add('touched'); showErr(i); });
  bad?.scrollIntoView({ block: 'center', behavior: 'smooth' }); bad?.focus({ preventScroll: true }); toast('Please complete the highlighted fields, or press Skip to come back later.');
  return false;
}
async function saveBasic(e) {
  e.preventDefault(); if (!pfValidate(e.target)) return;
  const body = {}; Object.values(PF.schema.basic).forEach(f => { const v = pfRead(f, 'b_'); if (v !== undefined) body[f.key] = v; });
  busy($('#pfSave'), true);
  try { PF.data = await api('/profile/basic', { method: 'PUT', body: JSON.stringify(body) }); PF.dirty = false; toast('Basic information saved.'); pfNext(); }
  catch (err) { toast(err.message); busy($('#pfSave'), false); }
}
function nameDialog() {
  const u = PF.data.user;
  formDialog('Change name', 'Your name is used across My Trial Board and on your CV. Enter your password to confirm the change; it is recorded in your history.',
    field('First name', 'n_first', { required: true, value: u.first, attrs: 'maxlength="60"' }) + field('Middle name', 'n_middle', { value: u.middle, attrs: 'maxlength="60"' }) + field('Last name', 'n_last', { required: true, value: u.last, attrs: 'maxlength="60"' }) + pwField('Your password', 'n_pw', { autocomplete: 'current-password' }), 'Save name',
    async (form, d) => { PF.data = await api('/profile/name', { method: 'POST', body: JSON.stringify({ first: $('#n_first').value, middle: $('#n_middle').value, last: $('#n_last').value, password: $('#n_pw').value }) }); d.close(); pfSoft(); if (state.me) state.me.user.name = PF.data.user.first + ' ' + PF.data.user.last; toast('Name updated.'); });
}
const CONTACT_LABEL = { email: 'primary email', phone: 'primary phone number', alt_email: 'alternate email' };
function contactDialog(channel, verifyExisting) {
  const u = PF.data.user, isPhone = channel === 'phone', label = CONTACT_LABEL[channel];
  const intro = channel === 'email' ? 'This is the email you sign in with. We will send a code to the new address; your email changes only after you enter it.' : isPhone ? 'We will send a code to the new number; it changes only after you enter the code.' : 'An alternate email can help recover your account and match your earlier records. We will send a code to it.';
  formDialog(`${verifyExisting ? 'Verify' : u[channel] ? 'Change' : 'Add'} ${label}`, intro,
    field(isPhone ? 'New phone number' : 'Email address', 'c_value', { required: true, full: true, type: isPhone ? 'tel' : 'email', value: verifyExisting ? u.alt_email : '', attrs: isPhone ? PHONE : 'maxlength="160"' }) + pwField('Your password', 'c_pw', { autocomplete: 'current-password', full: true }), 'Send code',
    async (form, d) => {
      const r = await api('/profile/contact/request', { method: 'POST', body: JSON.stringify({ channel, value: $('#c_value').value.trim(), password: $('#c_pw').value }) });
      PF.data.pending_contact[channel] = r.sent_to; d.close(); pfSoft(); contactCodeDialog(channel, r.phone_code_on_screen);
    });
}
function contactCodeDialog(channel, screenCode) {
  const to = PF.data.pending_contact[channel];
  formDialog('Enter the code', `We sent a 6-digit code to <b>${esc(to)}</b>. It is valid for 15 minutes.${screenCode ? `<br><span class="dev-inline">SMS is not connected yet. Your code is <b>${esc(screenCode)}</b>.</span>` : ''}`,
    field('Code', 'c_code', { required: true, full: true, attrs: 'inputmode="numeric" maxlength="6" pattern="\\d{6}" autocomplete="one-time-code"' }) + (state.dev && channel !== 'phone' ? `<div class="field full"><button type="button" class="linkish" onclick="showTestCodeFor('${esc(to)}')">Show test code</button></div>` : ''), 'Verify',
    async (form, d) => { PF.data = await api('/profile/contact/verify', { method: 'POST', body: JSON.stringify({ channel, code: $('#c_code').value.trim() }) }); d.close(); pfSoft(); if (channel === 'email' && state.me) state.me.user.email = PF.data.user.email; toast(`Your ${CONTACT_LABEL[channel]} is verified and saved.`); });
}
async function showTestCodeFor(target) {
  try { const r = await api('/dev/outbox'), m = r.messages.find(x => x.target === target), code = m && /\d{6}/.exec(m.body); if (code) { $('#c_code').value = code[0]; toast('Test code filled in.'); } else toast('No code found yet.'); } catch (e) { toast(e.message); }
}
function removeAltEmail() {
  formDialog('Remove alternate email', `Remove <b>${esc(PF.data.user.alt_email)}</b> from your account?`, pwField('Your password', 'c_pw', { autocomplete: 'current-password', full: true }), 'Remove',
    async (form, d) => { await api('/profile/contact/request', { method: 'POST', body: JSON.stringify({ channel: 'alt_email', value: '', password: $('#c_pw').value }) }); PF.data = await api('/profile'); d.close(); pfSoft(); toast('Alternate email removed.'); });
}

/* ---------- Step 2: About ---------- */
function aboutStep() {
  const about = PF.data.about;
  return `<form id="pfForm" onsubmit="saveAbout(event)" novalidate><div class="field full"><label for="a_about">Professional summary</label><textarea id="a_about" rows="9" maxlength="4000" placeholder="For example: Consultant cardiologist with 12 years of clinical research experience as Principal Investigator in phase II–IV cardiovascular trials…" oninput="$('#aCount').textContent=this.value.length">${esc(about)}</textarea><small class="help"><span id="aCount">${about.length}</span> / 4000 characters. Aim for at least a few sentences.</small></div>
  ${PF.schema.ai ? `<div class="pf-ai"><button type="button" class="btn ghost min" id="aSuggest" onclick="suggestAbout()">✦ Suggest a clearer wording</button><small class="muted">AI only suggests. Nothing changes unless you choose to use it.</small></div><div id="aSuggestion"></div>` : ''}${pfControls('Save & continue ↗')}</form>`;
}
async function suggestAbout() {
  const btn = $('#aSuggest'); busy(btn, true);
  try {
    const r = await api('/profile/about/suggest', { method: 'POST', body: JSON.stringify({ about: $('#a_about').value }) });
    $('#aSuggestion').innerHTML = `<div class="pf-suggest"><div class="eyebrow">Suggestion</div><p id="aSuggestText"></p><div class="pf-inline"><button type="button" class="btn primary min" onclick="useSuggestion()">Use this text</button><button type="button" class="btn ghost min" onclick="$('#aSuggestion').innerHTML=''">Dismiss</button></div><small class="muted">Check every fact before saving. You can still edit it.</small></div>`;
    $('#aSuggestText').textContent = r.suggestion;
  } catch (e) { toast(e.message); }
  busy(btn, false);
}
function useSuggestion() { const t = $('#a_about'); t.value = $('#aSuggestText').textContent; $('#aCount').textContent = t.value.length; $('#aSuggestion').innerHTML = ''; PF.dirty = true; t.focus(); }
async function saveAbout(e) {
  e.preventDefault(); busy($('#pfSave'), true);
  try { PF.data = await api('/profile/about', { method: 'PUT', body: JSON.stringify({ about: $('#a_about').value }) }); PF.dirty = false; toast('Summary saved.'); pfNext(); }
  catch (err) { toast(err.message); busy($('#pfSave'), false); }
}

/* ---------- Expertise steps (multi-select) ---------- */
function tagsStep(key) {
  const T = PF.schema.tags[key], values = PF.data[key], na = PF.data.na.includes(key);
  return `<form id="pfForm" onsubmit="saveTags(event,'${key}')" novalidate>${pfChips({ label: PF.schema.steps[PF.step].title, options: T.options, other: true }, 't_' + key, values)}${values.length ? '' : pfNothing(key, na)}${pfControls('Save & continue ↗')}</form>`;
}
const pfNothing = (key, na) => `<label class="check pf-na"><input type="checkbox" ${na ? 'checked' : ''} onchange="pfSetNA('${key}',this)"> I have nothing to add in this section</label>`;
async function saveTags(e, key) {
  e.preventDefault(); busy($('#pfSave'), true);
  try { PF.data = await api('/profile/tags/' + key, { method: 'PUT', body: JSON.stringify({ values: pfReadChips('t_' + key) }) }); PF.dirty = false; toast('Saved.'); pfNext(); }
  catch (err) { toast(err.message); busy($('#pfSave'), false); }
}

/* ---------- Repeating sections: cards, add / edit / delete, CSV ---------- */
function cardParts(S, data, keys) {
  const types = Object.fromEntries(S.fields.map(f => [f.key, f.type]));
  return (keys || []).map(k => {
    const key = k.key || k; let v = data[key];
    if (Array.isArray(v)) v = v.join(', ');
    return v == null || v === '' || v === false ? null : (k.prefix || '') + (['date', 'month'].includes(types[key]) ? showDate(v) : String(v));
  }).filter(Boolean);
}
// Same rules as card_view() on the server.
function cardView(S, data) {
  const c = S.card; let meta = cardParts(S, data, c.meta);
  if (c.present && data[c.present]) meta = meta.slice(0, 1).concat('Present');
  return { title: data[c.title] || '', tag: data[c.tag] || '', sub: cardParts(S, data, c.sub).join(' · '), meta: meta.join(c.meta_join || ' · '), text: data[c.text] || '', link: data[c.link] || '' };
}
const SOURCE_BADGE = { cv: 'From CV', csv: 'From CSV', registration: 'MTB membership' };
function entryCardHTML(S, e) {
  const c = cardView(S, e.data), roles = S.key === 'place_of_work' && e.data.research_roles?.length ? e.data.research_roles.map(noOthers).join(', ') : '';
  return `<div class="pf-entry ${e.expired ? 'expired' : ''}"><div class="pf-entry-main"><div class="pf-entry-title">${esc(noOthers(c.title))}${c.tag ? ` <span class="tag">${esc(noOthers(c.tag))}</span>` : ''}${e.expired ? ' <span class="pill rejected">Expired</span>' : ''}${SOURCE_BADGE[e.source] ? ` <span class="pf-src">${SOURCE_BADGE[e.source]}</span>` : ''}</div>${c.sub || roles ? `<div class="sub">${esc(noOthers([c.sub, roles].filter(Boolean).join(' · ')))}</div>` : ''}${c.text ? `<p class="pf-entry-text">${esc(c.text)}</p>` : ''}${c.link ? `<a class="pf-link" href="${esc(c.link)}" target="_blank" rel="noopener noreferrer">${esc(c.link)}</a>` : ''}${e.file ? `<a class="pf-doc" href="/api/profile/files/${e.file.id}" target="_blank" rel="noopener">📎 ${esc(e.file.name)} <small>(${pfBytes(e.file.size)})</small></a>` : ''}</div>
  <div class="pf-entry-side">${c.meta ? `<span class="pf-meta">${esc(c.meta)}</span>` : ''}<span class="row-actions"><button type="button" class="btn ghost min" onclick="entryDialog('${S.key}',${e.id})">Edit</button>${e.locked ? '' : `<button type="button" class="btn ghost min danger" onclick="entryDelete('${S.key}',${e.id})">Delete</button>`}</span></div></div>`;
}
function entryListHTML(key) {
  const S = pfSec(key), all = PF.data.entries[key], q = PF.search.trim().toLowerCase();
  const list = q ? all.filter(e => JSON.stringify(e.data).toLowerCase().includes(q)) : all;
  if (!all.length) return `<div class="pf-empty"><b>No ${esc(S.item)} added yet.</b><p class="sub">Use “Add ${esc(S.item)}”${S.csv ? ', import a CSV file' : ''}${PF.schema.ai && key !== 'attachment' ? ' or upload your CV to fill this in' : ''}.</p>${PF.schema.can_skip.includes(key) ? pfNothing(key, PF.data.na.includes(key)) : ''}</div>`;
  return list.length ? list.map(e => entryCardHTML(S, e)).join('') : `<div class="pf-empty"><p class="sub">Nothing matches “${esc(PF.search)}”.</p></div>`;
}
function entriesStep(key) {
  const S = pfSec(key), n = PF.data.entries[key].length;
  return `<div class="pf-toolbar"><div class="pf-inline"><button type="button" class="btn primary min" id="pfAdd" onclick="entryDialog('${key}')">+ Add ${esc(S.item)}</button>${S.csv ? `<label class="btn ghost min pf-filebtn">Import CSV<input type="file" id="pfCsv" accept=".csv,text/csv" onchange="csvImport('${key}',this)"></label><a class="linkish" href="/api/profile/entries/${key}/csv-template" download>Download CSV template</a>` : ''}</div>${n > 3 ? `<input class="pf-search" type="search" placeholder="Search ${n} entries" value="${esc(PF.search)}" aria-label="Search" oninput="PF.search=this.value;$('#pfList').innerHTML=entryListHTML('${key}')">` : ''}</div>
  <div id="pfList" class="pf-list">${entryListHTML(key)}</div>${pfControls('')}`;
}
function fileBoxHTML(S, file) {
  const need = S.file_required ? REQ : ' <small class="help">optional</small>';
  return `<div class="field full" id="e_filebox" data-file="${file ? file.id : ''}" data-kind="${S.file_kind}"><label>${esc(S.file)}${need}</label>${file
    ? `<div class="pf-file-have">📎 <a href="/api/profile/files/${file.id}" target="_blank" rel="noopener">${esc(file.name)}</a> <small class="muted">(${pfBytes(file.size)})</small><button type="button" class="linkish" onclick="entryFileClear()">Remove</button></div>`
    : `<label class="drop"><input type="file" id="e_file" onchange="entryFilePicked(this)"><span class="drop-icon">⇪</span><span>Choose ${esc(S.file_rule)}.</span></label>`}<small class="err" aria-live="polite"></small></div>`;
}
let entryCtx = null;
async function entryFilePicked(input) {
  const file = input.files[0], box = $('#e_filebox'); if (!file) return;
  box.querySelector('.drop').classList.add('busy');
  try { const r = await apiUpload('/profile/files', { kind: box.dataset.kind, file }); box.outerHTML = fileBoxHTML(entryCtx.S, r.file); }
  catch (e) { toast(e.message); input.value = ''; box.querySelector('.drop').classList.remove('busy'); }
}
function entryFileClear() { $('#e_filebox').outerHTML = fileBoxHTML(entryCtx.S, null); }
// Add or edit one entry. With o.local the result goes back to the CV review instead of the server.
function entryDialog(key, id, o = {}) {
  const S = pfSec(key), entry = o.local ? { data: o.data } : id ? PF.data.entries[key].find(e => e.id === id) : null;
  const data = entry?.data || (key === 'place_of_work' ? { status: 'Current' } : {}), fixed = entry?.locked ? ['org_type', 'org_name', 'org_subtype', 'status'] : [];
  const fields = S.fields.filter(f => !fixed.includes(f.key));
  entryCtx = { S, key, id, fields, o };
  const lockedNote = entry?.locked ? `<div class="soft-note full pf-note"><b>${esc(data.org_name)}</b> · ${esc(data.org_type)} · ${esc(data.status)}<br>This organization is linked to your My Trial Board membership, so its name, type and status are kept in step with it. You can add the other details.</div>` : '';
  const d = openDialog(`${entry ? 'Edit' : 'Add'} ${esc(S.item)}`, `<form class="dlg-form" id="entryForm" novalidate><div class="form-grid">${lockedNote}${fields.map(f => pfField(f, data[f.key], 'e_')).join('')}${S.file && !o.local ? fileBoxHTML(S, entry?.file) : ''}</div><div class="controls"><button type="button" class="btn ghost" data-close>Cancel</button><button class="btn primary" type="submit" id="entrySave">${o.local ? 'Use these details' : 'Save'}</button></div></form>`);
  d.el.querySelector('.modal').classList.add('pf-modal');
  entryCtx.dialog = d;
  const cur = $('#e_current'), end = $('#e_end');
  if (cur && end) { const sync = () => { end.disabled = cur.checked; if (cur.checked) end.value = ''; }; cur.addEventListener('change', sync); sync(); }
  const org = $('#e_org_name');
  if (org) org.addEventListener('input', orgSuggest);
  d.el.querySelector('form').addEventListener('submit', entrySubmit);
}
let orgTimer = null, orgHits = [];
function orgSuggest(e) {
  const input = e.target, hit = orgHits.find(o => o.name === input.value);
  if (hit) { const t = $('#e_org_type'); if (t && !t.value) t.value = hit.type; return; }
  clearTimeout(orgTimer);
  orgTimer = setTimeout(async () => {
    if (input.value.trim().length < 2) return;
    try { orgHits = (await api('/profile/org-search?q=' + encodeURIComponent(input.value.trim()))).results; $('#e_org_name_dl').innerHTML = orgHits.map(o => `<option value="${esc(o.name)}">${esc(o.type)} · ${esc(o.city)} · on My Trial Board</option>`).join(''); } catch {}
  }, 250);
}
async function entrySubmit(ev, allowDuplicate) {
  ev?.preventDefault();
  const { S, key, id, fields, o, dialog } = entryCtx, form = $('#entryForm');
  if (!form.checkValidity()) { form.querySelectorAll(':invalid').forEach(i => { i.classList.add('touched'); showErr(i); }); form.querySelector(':invalid')?.focus(); return; }
  const data = {}; fields.forEach(f => { const v = pfRead(f, 'e_'); if (v !== undefined) data[f.key] = v; });
  if (o.local) { dialog.close(); return o.onSave(data); }
  const fileId = $('#e_filebox')?.dataset.file || null;
  if (S.file_required && !fileId) { $('#e_filebox .err').textContent = 'Please choose the file to attach.'; return; }
  const btn = $('#entrySave'); busy(btn, true);
  try {
    PF.data = await api(`/profile/entries/${key}${id ? '/' + id : ''}`, { method: id ? 'PUT' : 'POST', body: JSON.stringify({ data, file_id: fileId, allow_duplicate: !!allowDuplicate }) });
    dialog.close(); toast(id ? 'Changes saved.' : `${S.item[0].toUpperCase() + S.item.slice(1)} added.`); render();
  } catch (err) {
    busy(btn, false);
    if (err.data?.code === 'duplicate') return confirmDialog('Possible duplicate', `${esc(err.message)} Save it anyway?`, 'Save anyway', () => entrySubmit(null, true));
    toast(err.message);
  }
}
function entryDelete(key, id) {
  const S = pfSec(key), e = PF.data.entries[key].find(x => x.id === id);
  confirmDialog(`Delete this ${esc(S.item)}?`, `<b>${esc(noOthers(cardView(S, e.data).title))}</b> will be removed from your profile${e.file ? ' together with its file' : ''}. The removal is kept in your change history.`, 'Delete',
    async () => { PF.data = await api(`/profile/entries/${key}/${id}`, { method: 'DELETE', body: '{}' }); toast('Removed.'); render(); }, true);
}
async function csvImport(key, input) {
  const file = input.files[0]; if (!file) return;
  const label = input.closest('label'); label.classList.add('busy');
  try {
    const r = await api(`/profile/entries/${key}/csv`, { method: 'POST', body: JSON.stringify({ csv: await file.text() }) });
    PF.data = r.profile; render();
    const rows = (title, list, line) => list.length ? `<h4>${title}</h4><ul class="pf-report">${list.map(line).join('')}</ul>` : '';
    openDialog('CSV import result', `<div class="info-body"><p><b>${r.added}</b> ${r.added === 1 ? 'row was' : 'rows were'} added to ${esc(pfSec(key).title)}.</p>${rows(`Not imported: ${r.invalid.length} with problems`, r.invalid, x => `<li><b>Row ${x.row}</b>: ${esc(x.errors.join('; '))}</li>`)}${rows(`Skipped: ${r.duplicates.length} already in your profile`, r.duplicates, x => `<li><b>Row ${x.row}</b>: ${esc(noOthers(x.label))}</li>`)}${r.invalid.length ? '<p class="sub">Correct those rows in your file and import it again; rows already added are skipped as duplicates.</p>' : ''}</div>`, `<span></span><button class="btn primary" type="button" data-close>Done</button>`);
  } catch (e) { toast(e.message); label.classList.remove('busy'); input.value = ''; }
}

/* ---------- CV upload and AI-assisted auto-fill (BRD 5) ---------- */
let cvDialog = null;
function cvUploadDialog() {
  if (!PF.schema.ai) return openDialog('CV auto-fill is not switched on', `<div class="info-body"><p>Reading a CV needs the AI service key, which has not been added to this site yet. You can still fill in every section by hand or import CSV files.</p>${state.dev ? '<p class="dev">Site administrator: add <code>OPENAI_API_KEY=…</code> to the <code>.env</code> file and restart the server.</p>' : ''}</div>`, `<span></span><button class="btn primary" type="button" data-close>OK</button>`);
  const had = PF.data.cv?.has_file;
  cvDialog = openDialog('Upload CV to auto-fill your profile', `<div id="cvBody"><p class="sub">We read your CV and suggest entries for each section. You review everything first: <b>nothing is saved until you confirm it.</b></p>
    <label class="drop pf-cvdrop" id="cvDrop"><input type="file" id="cvFile" accept=".pdf,.doc,.docx,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document" onchange="cvPicked(this)"><span class="drop-icon">⇪</span><span id="cvName"><b>Choose your CV</b><br>PDF, DOC or DOCX, up to 10 MB. Any layout works, including scanned PDFs.</span></label>
    <ul class="pf-points"><li>Your registered name and your verified email and phone are never changed by a CV.</li><li>Entries you already have stay as they are. Likely duplicates are pointed out.</li><li>Clinical trials listed in a CV are not added as verified trial experience.</li><li>The file is read by an AI service (OpenAI) and stored privately on My Trial Board${had ? '; it replaces the CV you uploaded before' : ''}.</li></ul></div>`,
    `<button class="btn ghost" type="button" data-close>Cancel</button><button class="btn primary" type="button" id="cvGo" disabled onclick="cvUpload()">Read my CV ↗</button>`);
  cvDialog.el.querySelector('.modal').classList.add('pf-modal');
}
function cvPicked(input) {
  const f = input.files[0];
  $('#cvName').innerHTML = f ? `<b>${esc(f.name)}</b><br>${pfBytes(f.size)} · ready to read` : '<b>Choose your CV</b>';
  $('#cvGo').disabled = !f;
}
const cvProgressHTML = name => `<div class="pf-reading"><span class="pf-spin big"></span><h3>Reading your CV…</h3><p class="sub">${esc(name)}<br>This usually takes under a minute. You can close this window and keep working: we will tell you when the review is ready.</p></div>`;
async function cvUpload() {
  const file = $('#cvFile').files[0], btn = $('#cvGo'); if (!file) return;
  busy(btn, true);
  try {
    const r = await apiUpload('/profile/cv', { file });
    PF.data.cv = { id: r.import_id, status: 'processing', file_name: file.name, has_file: true };
    $('#cvBody').innerHTML = cvProgressHTML(file.name); btn.remove(); cvDialog.el.querySelector('.controls [data-close]').textContent = 'Close';
    pfSoft(); cvWatch(r.import_id);
  } catch (e) { toast(e.message); busy(btn, false); }
}
// Ask every few seconds whether the reading has finished.
function cvWatch(id) {
  clearInterval(PF.poll);
  PF.poll = setInterval(async () => {
    let r; try { r = await api('/profile/cv/' + id); } catch { return; }
    if (r.status === 'processing') return;
    clearInterval(PF.poll); PF.poll = null;
    if (!PF.data || PF.data.cv?.id !== id) return;
    PF.data.cv.status = r.status; PF.data.cv.error = r.error;
    const open = cvDialog && document.body.contains(cvDialog.el);
    if (r.status === 'ready' && open && state.page === 'profile') { cvDialog.close(); return cvStartReview(r); }
    if (open) cvDialog.close();
    if (state.page === 'profile' && !PF.review) pfSoft();
    toast(r.status === 'ready' ? 'Your CV has been read. Open My Profile to review it.' : r.error || 'Your CV could not be read.');
  }, 2500);
}
async function cvOpenReview(id) { try { cvStartReview(await api('/profile/cv/' + id)); } catch (e) { toast(e.message); } }
async function cvDiscard(id, quiet) {
  const run = async () => { PF.data = await api(`/profile/cv/${id}/discard`, { method: 'POST', body: '{}' }); PF.review = null; render(); };
  if (quiet) return run().catch(e => toast(e.message));
  confirmDialog('Discard this CV review?', 'Nothing from this CV will be added to your profile. You can upload the CV again later.', 'Discard', run, true);
}
function cvStartReview(r) {
  if (r.status !== 'ready') return toast(r.error || 'This CV review is no longer open.');
  const p = r.preview;
  PF.review = {
    id: r.id, file: r.file_name,
    basic: p.basic.map(x => ({ ...x, on: x.kind === 'new' || x.kind === 'add', value: Array.isArray(x.proposed) ? [...x.proposed] : x.proposed })),
    about: p.about && { ...p.about, on: !p.about.current, value: p.about.proposed },
    tags: { trial_expertise: p.trial_expertise.map(v => ({ v, on: true })), tech_expertise: p.tech_expertise.map(v => ({ v, on: true })) },
    sections: Object.fromEntries(Object.entries(p.sections).map(([k, items]) => [k, items.map(it => ({ ...it, on: !it.duplicate && !it.missing.length }))])),
  };
  state.page = 'profile'; render(); window.scrollTo(0, 0);
}
function rvCount() {
  const R = PF.review;
  return R.basic.filter(x => x.on && x.kind !== 'locked').length + (R.about?.on ? 1 : 0) + Object.values(R.tags).flat().filter(t => t.on).length + Object.values(R.sections).flat().filter(i => i.on).length;
}
const rvCountHTML = () => { const n = rvCount(); return n ? `<b>${n}</b> ${n === 1 ? 'item' : 'items'} selected to add` : 'Nothing selected yet'; };
function rvTouch() { $('#rvCount').innerHTML = rvCountHTML(); $('#rvSave').disabled = !rvCount(); }
function rvBasicRow(x, i) {
  if (x.kind === 'locked') return `<tr class="rv-locked"><td></td><th scope="row">${esc(x.label)}</th><td>${esc(x.current)}</td><td>${esc(x.proposed)}<small class="help">${esc(x.note)}</small></td></tr>`;
  const list = Array.isArray(x.proposed);
  const cur = list ? (x.current.length ? esc(x.current.map(noOthers).join(', ')) : '<span class="muted">None yet</span>') : (x.current ? esc(x.current) : '<span class="muted">Empty</span>');
  const val = list ? `<div class="chip-row">${x.proposed.map((v, j) => `<label class="chip"><input type="checkbox" ${x.value.includes(v) ? 'checked' : ''} onchange="rvBasicList(${i},${j},this.checked)"><span>${esc(noOthers(v))}</span></label>`).join('')}</div>` : `<input value="${esc(x.value)}" maxlength="160" aria-label="${esc(x.label)} from your CV" oninput="PF.review.basic[${i}].value=this.value">`;
  return `<tr><td><input type="checkbox" class="rv-box" ${x.on ? 'checked' : ''} onchange="PF.review.basic[${i}].on=this.checked;rvTouch()" aria-label="Use ${esc(x.label)} from the CV"></td><th scope="row">${esc(x.label)}${x.kind === 'conflict' ? '<span class="pill pending">Different</span>' : ''}</th><td>${cur}</td><td>${val}${x.note ? `<small class="help">${esc(x.note)}</small>` : ''}</td></tr>`;
}
function rvBasicList(i, j, on) { const x = PF.review.basic[i], v = x.proposed[j]; x.value = on ? [...new Set([...x.value, v])] : x.value.filter(y => y !== v); x.on = x.value.length > 0; rvTouch(); }
function rvItemHTML(key, i) {
  const S = pfSec(key), it = PF.review.sections[key][i], c = cardView(S, it.data);
  return `<div class="pf-entry rv ${it.on ? 'on' : ''}"><input type="checkbox" class="rv-box" ${it.on ? 'checked' : ''} onchange="rvToggle('${key}',${i},this.checked)" aria-label="Add ${esc(noOthers(c.title))} to my profile"><div class="pf-entry-main"><div class="pf-entry-title">${esc(noOthers(c.title))}${c.tag ? ` <span class="tag">${esc(noOthers(c.tag))}</span>` : ''}${it.duplicate ? ' <span class="pill pending">Already in your profile</span>' : ''}${it.missing.length ? ` <span class="pill rejected">Needs: ${esc(it.missing.join(', '))}</span>` : ''}</div>${c.sub ? `<div class="sub">${esc(noOthers(c.sub))}</div>` : ''}${c.text ? `<p class="pf-entry-text">${esc(c.text)}</p>` : ''}${c.link ? `<span class="pf-link">${esc(c.link)}</span>` : ''}</div><div class="pf-entry-side">${c.meta ? `<span class="pf-meta">${esc(c.meta)}</span>` : ''}<button type="button" class="btn ghost min" onclick="rvEdit('${key}',${i})">Edit</button></div></div>`;
}
const rvSectionHTML = key => PF.review.sections[key].map((_, i) => rvItemHTML(key, i)).join('');
function rvToggle(key, i, on) {
  const it = PF.review.sections[key][i];
  if (on && it.missing.length) { $('#rv_' + key).innerHTML = rvSectionHTML(key); toast(`Add the missing details first: ${it.missing.join(', ')}.`); return rvEdit(key, i); }
  it.on = on; $('#rv_' + key).innerHTML = rvSectionHTML(key); rvTouch();
}
function rvEdit(key, i) {
  const it = PF.review.sections[key][i], S = pfSec(key);
  entryDialog(key, null, { local: true, data: it.data, onSave: data => {
    Object.keys(data).forEach(k => { if (data[k] === '' || (Array.isArray(data[k]) && !data[k].length) || data[k] === false) delete data[k]; });
    it.data = data; it.missing = S.fields.filter(f => f.required && !data[f.key]).map(f => f.label); it.on = !it.missing.length;
    $('#rv_' + key).innerHTML = rvSectionHTML(key); rvTouch();
  } });
}
function rvAll(key, on) { PF.review.sections[key].forEach(it => { it.on = on && !it.missing.length; }); $('#rv_' + key).innerHTML = rvSectionHTML(key); rvTouch(); }
function reviewPage() {
  const R = PF.review, keys = Object.keys(R.sections), found = keys.reduce((n, k) => n + R.sections[k].length, 0);
  const card = (title, sub, body, tools = '') => `<section class="card pf-card rv-card"><div class="pf-step-head"><div><h3>${title}</h3>${sub ? `<p class="sub">${sub}</p>` : ''}</div>${tools}</div>${body}</section>`;
  const tagCard = key => R.tags[key].length ? card(esc(PF.schema.steps.find(s => s.key === key).title), 'Suggested from your CV. Untick anything that does not apply.', `<div class="chip-row">${R.tags[key].map((t, i) => `<label class="chip"><input type="checkbox" ${t.on ? 'checked' : ''} onchange="PF.review.tags.${key}[${i}].on=this.checked;rvTouch()"><span>${esc(t.v)}</span></label>`).join('')}</div>`) : '';
  const empty = !R.basic.length && !R.about && !found && !R.tags.trial_expertise.length && !R.tags.tech_expertise.length;
  return `<div class="pf pf-review"><div class="pf-head"><div><div class="overline">CV review</div><h2>Check what we found in your CV</h2><p class="sub">From <b>${esc(R.file)}</b>. Tick what should go into your profile and edit anything that is not quite right. Nothing is saved until you press <b>Save confirmed fields</b>.</p></div></div>
  ${empty ? card('Nothing new was found', 'Everything in this CV is already in your profile, or the file had no details we could use.', '') : ''}
  ${R.basic.length ? card('Basic Information', 'Where the CV differs from your profile, both values are shown. Tick a row to use the CV value.', `<div class="table-wrap"><table class="rv-table"><thead><tr><th></th><th>Field</th><th>In your profile now</th><th>From your CV</th></tr></thead><tbody>${R.basic.map(rvBasicRow).join('')}</tbody></table></div>`) : ''}
  ${R.about ? card('About', R.about.drafted ? 'Your CV has no summary, so this draft was written from its contents. Check every fact.' : 'Taken from the summary in your CV.', `<label class="check"><input type="checkbox" class="rv-box" ${R.about.on ? 'checked' : ''} onchange="PF.review.about.on=this.checked;rvTouch()"> ${R.about.current ? 'Replace my current summary with this text' : 'Use this as my summary'}</label><div class="field full"><textarea rows="6" maxlength="4000" aria-label="Summary from your CV" oninput="PF.review.about.value=this.value">${esc(R.about.value)}</textarea></div>${R.about.current ? `<div class="soft-note pf-note"><b>Your current summary</b><br>${esc(R.about.current)}</div>` : ''}`) : ''}
  ${tagCard('trial_expertise')}${tagCard('tech_expertise')}
  ${keys.map(k => card(esc(pfSec(k).title), `${R.sections[k].length} found`, `<div class="pf-list" id="rv_${k}">${rvSectionHTML(k)}</div>`, `<span class="pf-inline"><button type="button" class="linkish" onclick="rvAll('${k}',true)">Select all</button><button type="button" class="linkish" onclick="rvAll('${k}',false)">Clear</button></span>`)).join('')}
  <div class="pf-savebar"><span id="rvCount">${rvCountHTML()}</span><span class="pf-inline"><button type="button" class="btn ghost" onclick="cvDiscard(${R.id})">Discard</button><button type="button" class="btn ghost" onclick="rvLater()">Finish later</button><button type="button" class="btn primary" id="rvSave" ${rvCount() ? '' : 'disabled'} onclick="rvSave()">Save confirmed fields ↗</button></span></div></div>`;
}
function rvLater() { PF.review = null; render(); toast('Your CV review is kept. Use “Review now” on My Profile to come back to it.'); }
async function rvSave() {
  const R = PF.review, btn = $('#rvSave');
  const body = { basic: {}, about: R.about?.on ? R.about.value : null, entries: {} };
  R.basic.forEach(x => { if (x.on && x.kind !== 'locked') body.basic[x.key] = x.value; });
  Object.keys(R.tags).forEach(k => { body[k] = R.tags[k].filter(t => t.on).map(t => t.v); });
  Object.keys(R.sections).forEach(k => { const items = R.sections[k].filter(i => i.on).map(i => ({ data: i.data, keep_duplicate: !!i.duplicate })); if (items.length) body.entries[k] = items; });
  busy(btn, true);
  try {
    const r = await api(`/profile/cv/${R.id}/apply`, { method: 'POST', body: JSON.stringify(body) });
    PF.data = r.profile; PF.review = null; PF.step = 0; render(); window.scrollTo(0, 0);
    const n = r.saved.basic + r.saved.entries;
    toast(`${n} ${n === 1 ? 'item' : 'items'} added to your profile from your CV.${r.saved.skipped_duplicates ? ` ${r.saved.skipped_duplicates} duplicate skipped.` : ''} Go through the steps to check and complete it.`);
  } catch (e) { toast(e.message); busy(btn, false); }
}

/* ---------- Declaration with e-signature (BRD 21) ---------- */
function declarationStep() {
  const d = PF.data, dec = d.declaration, steps = PF.schema.steps.filter(s => !['declaration', 'attachment'].includes(s.key)), done = d.completion.steps;
  const open = steps.filter(s => !done[s.key]);
  const list = `<div class="pf-check-grid">${steps.map(s => `<button type="button" class="pf-checkrow ${done[s.key] ? 'done' : ''}" onclick="pfGoKey('${s.key}')"><i>${done[s.key] ? '✓' : '○'}</i>${esc(s.title)}${done[s.key] ? '' : '<small>Not filled in</small>'}</button>`).join('')}</div>`;
  const signed = dec.signed_at && !dec.changed_since;
  const name = [d.user.first, d.user.middle, d.user.last].filter(Boolean).join(' ');
  const form = `<form id="declForm" onsubmit="signDeclaration(event)" novalidate><div class="pf-declare">${esc(PF.schema.declaration.text)}</div>
    <label class="check"><input type="checkbox" id="d_agree" required> <span>I have read and agree to this declaration.${REQ}</span></label>
    <div class="form-grid"><div class="field"><label>User name</label><input value="${esc(name)}" readonly tabindex="-1"><small class="help">From your account</small></div><div class="field"><label>Date and time</label><input value="${esc(pfWhen(new Date()))}" readonly tabindex="-1"><small class="help">Recorded by the system when you confirm</small></div>
    ${field('Type your full name to sign', 'd_name', { required: true, placeholder: name, attrs: 'autocomplete="off" maxlength="200"' })}${pwField('Your password', 'd_pw', { autocomplete: 'current-password' })}</div>
    <p class="sub">Typing your name and entering your password is your electronic signature. It is recorded with the date, time and version of this declaration.</p>
    <div class="controls pf-controls"><button type="button" class="btn ghost" onclick="pfBack()">← Back</button><button class="btn primary" type="submit" id="declBtn">Confirm Profile ✓</button></div></form>`;
  return `${open.length ? `<div class="alert warn">${open.length} ${open.length === 1 ? 'section is' : 'sections are'} not filled in yet. You can still confirm what you have, or open a section below to complete it first.</div>` : ''}${list}
  ${signed ? `<div class="pf-signed"><div class="pf-signed-mark">✓</div><div><b>Profile confirmed</b><p>Signed electronically by <b>${esc(dec.name)}</b> on ${esc(pfWhen(dec.signed_at))} · declaration v${esc(dec.version)}</p><p class="sub">You can keep updating your profile. After a change you will be asked to confirm it again.</p></div></div><div class="controls pf-controls"><button type="button" class="btn ghost" onclick="pfBack()">← Back</button><button type="button" class="btn primary" onclick="exportDialog()">Export Profile as CV ↗</button></div>`
    : `${dec.signed_at ? `<div class="alert warn">You last signed on ${esc(pfWhen(dec.signed_at))} and have changed your profile since. Please confirm it again.</div>` : ''}${form}`}`;
}
async function signDeclaration(e) {
  e.preventDefault(); const form = e.target;
  if (!form.checkValidity()) { form.querySelectorAll(':invalid').forEach(i => { i.classList.add('touched'); showErr(i); }); return toast($('#d_agree').checked ? 'Type your full name and password to sign.' : 'Tick the declaration to confirm your profile.'); }
  busy($('#declBtn'), true);
  try { PF.data = await api('/profile/declaration', { method: 'POST', body: JSON.stringify({ agree: $('#d_agree').checked, full_name: $('#d_name').value, password: $('#d_pw').value }) }); render(); toast('Profile confirmed and signed.'); }
  catch (err) { toast(err.message); busy($('#declBtn'), false); }
}

/* ---------- Change history ---------- */
const PF_ACTIONS = { profile_updated: 'Details updated', profile_entry_added: 'Entry added', profile_entry_updated: 'Entry updated', profile_entry_removed: 'Entry removed', profile_csv_imported: 'CSV imported', profile_name_changed: 'Name changed', profile_contact_change_requested: 'Contact change started', profile_contact_changed: 'Contact detail changed', profile_visibility_changed: 'Team visibility changed', profile_file_removed: 'File removed', profile_declared: 'Declaration signed', profile_cv_exported: 'CV exported', profile_ai_rewrite_requested: 'AI wording suggestion requested', cv_uploaded: 'CV uploaded', cv_extraction_completed: 'CV read', cv_extraction_failed: 'CV could not be read', cv_import_applied: 'Details from CV saved', cv_import_discarded: 'CV review discarded' };
async function historyDialog() {
  let events; try { events = (await api('/profile/history')).events; } catch (e) { return toast(e.message); }
  const detail = e => {
    const d = e.details, sec = d.section ? PF.schema.steps.find(s => s.key === d.section)?.title || d.section : '';
    const changes = (d.changes || []).map(c => `<li><b>${esc(c.field)}</b>: ${c.old ? `<s>${esc(noOthers(c.old))}</s> → ` : ''}${c.new ? esc(noOthers(c.new)) : '<i>removed</i>'}</li>`).join('');
    const extra = e.action === 'profile_cv_exported' ? `${esc(d.template)} · ${esc(String(d.format).toUpperCase())}` : e.action === 'cv_uploaded' ? esc(d.file) : e.action === 'profile_declared' ? `Signed as ${esc(d.signed_name)} · ${esc(d.method)}` : e.action === 'profile_visibility_changed' ? (d.visible_to_team ? 'Shown to team' : 'Hidden from team') : e.action === 'cv_import_applied' ? `${d.basic + d.entries} items` : e.action === 'profile_csv_imported' ? `${d.added} added, ${d.invalid} invalid, ${d.duplicates} duplicates` : '';
    return `<div class="pf-hist"><div><b>${PF_ACTIONS[e.action] || esc(e.action)}</b>${sec ? ` <span class="tag">${esc(sec)}</span>` : ''}<span class="muted"> · ${esc(pfWhen(e.created))}</span></div>${extra ? `<div class="sub">${extra}</div>` : ''}${changes ? `<ul>${changes}</ul>` : ''}</div>`;
  };
  const d = openDialog('Change history', `<div class="pf-history-list">${events.length ? events.map(detail).join('') : '<p class="sub">No changes recorded yet.</p>'}</div>`, `<span class="sub">Latest ${events.length} changes to your profile</span><button class="btn primary" type="button" data-close>Close</button>`);
  d.el.querySelector('.modal').classList.add('pf-modal');
}

/* ---------- Export Profile as CV (BRD 22) ---------- */
let exportTimer = null;
function exportDialog() {
  const sc = PF.schema, tpl = sc.templates.find(t => !t.disabled).key;
  const d = openDialog('Export Profile as CV', `<div class="pf-export"><div class="pf-export-opts" id="exOpts">
    <fieldset><legend>CV template</legend>${sc.templates.map(t => `<label class="pf-radio ${t.disabled ? 'disabled' : ''}"><input type="radio" name="ex_tpl" value="${t.key}" ${t.key === tpl ? 'checked' : ''} ${t.disabled ? 'disabled' : ''}><span><b>${esc(t.name)}</b><small>${esc(t.note)}</small></span></label>`).join('')}</fieldset>
    <fieldset><legend>Sections to include</legend><div id="exSections"></div></fieldset>
    <fieldset><legend>Contact details to show</legend>${[['email', 'Email', 1], ['phone', 'Phone number', 1], ['location', 'City and country', 1], ['address', 'Full address', 0], ['alternate', 'Alternate email / phone', 0]].map(([k, l, on]) => `<label class="check"><input type="checkbox" data-contact="${k}" ${on ? 'checked' : ''}> ${l}</label>`).join('')}</fieldset>
    <p class="sub">Identity documents, uploaded certificates and attachments are never included.${PF.data.declaration.signed_at && !PF.data.declaration.changed_since ? '' : ' Your declaration is not signed for the current profile yet.'}</p></div>
    <div class="pf-export-view"><div class="pf-export-bar"><span class="eyebrow">Preview</span><span class="pf-inline"><button type="button" class="btn primary min" id="exPdf" onclick="exportDownload('pdf',this)">Download PDF</button><button type="button" class="btn ghost min" id="exDocx" onclick="exportDownload('docx',this)">Download Word (DOCX)</button></span></div><div class="pf-export-paper" id="exPreview"><p class="sub">Preparing preview…</p></div></div></div>`);
  d.el.querySelector('.modal').classList.add('pf-modal', 'wide');
  exportSections();
  $('#exOpts').addEventListener('change', e => { if (e.target.name === 'ex_tpl') exportSections(); clearTimeout(exportTimer); exportTimer = setTimeout(exportPreview, 200); });
  exportPreview();
}
function exportSections() {
  const sc = PF.schema, tpl = $('input[name=ex_tpl]:checked').value, d = PF.data;
  const has = k => k === 'about' ? !!d.about : sc.tags[k] ? d[k].length > 0 : d.entries[k].length > 0;
  const was = Object.fromEntries($$('#exSections input').map(i => [i.value, i.checked]));
  $('#exSections').innerHTML = sc.export_order[tpl].map(k => `<label class="check ${has(k) ? '' : 'muted'}"><input type="checkbox" value="${k}" ${has(k) && was[k] !== false ? 'checked' : ''} ${has(k) ? '' : 'disabled'}> ${esc(sc.export_titles[k])}${has(k) ? '' : ' <small>(empty)</small>'}</label>`).join('');
}
const exportOptions = () => ({ template: $('input[name=ex_tpl]:checked').value, sections: $$('#exSections input:checked').map(i => i.value), contact: Object.fromEntries($$('#exOpts [data-contact]').map(i => [i.dataset.contact, i.checked])) });
async function exportPreview() {
  const box = $('#exPreview'); if (!box) return;
  try { box.innerHTML = cvPreviewHTML(await api('/profile/export', { method: 'POST', body: JSON.stringify({ ...exportOptions(), format: 'preview' }) })); }
  catch (e) { box.innerHTML = `<p class="sub">${esc(e.message)}</p>`; }
}
function cvPreviewHTML(m) {
  const paras = t => t.split(/\n{2,}/).map(p => `<p>${esc(p).replace(/\n/g, '<br>')}</p>`).join('');
  const item = i => `<div class="cvp-item"><div class="cvp-row"><b>${esc(i.title)}${i.tag ? ` <small>${esc(i.tag)}</small>` : ''}</b><span>${esc(i.meta)}</span></div>${i.sub ? `<div class="cvp-sub">${esc(i.sub)}</div>` : ''}${i.text ? paras(i.text) : ''}${i.link ? `<div class="cvp-link">${esc(i.link)}</div>` : ''}</div>`;
  return `<div class="cvp ${m.template}">${m.template === 'clinical' ? '<div class="cvp-label">CURRICULUM VITAE</div>' : ''}<div class="cvp-name">${esc(m.name)}</div>${m.headline ? `<div class="cvp-headline">${esc(m.headline)}</div>` : ''}${m.contact.length ? `<div class="cvp-contact">${m.contact.map(esc).join(' &nbsp;|&nbsp; ')}</div>` : ''}<hr>${m.extras.map(([l, v]) => `<p class="cvp-extra"><b>${esc(l)}:</b> ${esc(v)}</p>`).join('')}
  ${m.blocks.map(b => `<div class="cvp-sec">${esc(b.title)}</div>${b.kind === 'text' ? paras(b.text) : b.kind === 'tags' ? `<p>${b.tags.map(esc).join(' &nbsp;·&nbsp; ')}</p>` : b.items.map(item).join('')}`).join('')}${m.blocks.length ? '' : '<p class="cvp-sub">No sections selected.</p>'}
  ${m.signature ? `<div class="cvp-sign"><p>I confirm that the information in this curriculum vitae is accurate and current.</p><div><span>Signature</span><i></i><span>Date</span><i class="short"></i></div></div>` : ''}<div class="cvp-foot">Generated from My Trial Board on ${esc(m.generated)}</div></div>`;
}
async function exportDownload(fmt, btn) {
  busy(btn, true);
  try {
    const res = await fetch('/api/profile/export', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': state.csrf }, body: JSON.stringify({ ...exportOptions(), format: fmt }) });
    if (!res.ok) { let j = {}; try { j = await res.json(); } catch {} throw Error(typeof j.detail === 'string' ? j.detail : 'The file could not be created.'); }
    const blob = await res.blob(), name = /filename="([^"]+)"/.exec(res.headers.get('Content-Disposition') || '')?.[1] || 'CV.' + fmt;
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = name; document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 10000);
    toast(`${name} downloaded.`);
  } catch (e) { toast(e.message); }
  busy(btn, false);
}

/* ---------- Team profiles (dashboard tab) and the read-only view of a teammate ---------- */
const personAvatar = (p, cls = '') => `<span class="pf-avatar ${cls}">${p.has_photo ? `<img src="/api/profile/people/${p.id}/photo" alt="" loading="lazy">` : esc(pfInitials(p.name))}</span>`;
function teamTab() {
  if (!PF.team || PF.team.org !== state.org) {
    const org = state.org; PF.team = { org, people: null };
    api('/profile/team/' + org).then(r => { if (PF.team?.org === org) { PF.team.people = r.people; if (state.page === 'dashboard' && state.tab === 'team') render(); } }).catch(e => toast(e.message));
  }
  const people = PF.team.people;
  return `<div class="toolbar"><h3>Team profiles</h3><button class="btn ghost min" onclick="openProfile()">Edit my profile</button></div><p class="sub pf-team-note">Professional profiles of the people in this organization. Each person chooses which sections their team can see; contact details, identity documents and files are never shown here.</p>${!people ? '<div class="card"><p class="sub">Loading…</p></div>' : `<div class="pf-team">${people.map(p => `<button type="button" class="pf-person" onclick="openPerson(${p.id})">${personAvatar(p)}<span class="pf-person-text"><b>${esc(p.name)}${p.me ? ' <span class="tag">You</span>' : ''}</b><small>${esc([p.designation, p.department].filter(Boolean).join(' · ') || p.role)}</small>${p.research_roles.length ? `<small class="pf-roles">${p.research_roles.map(esc).join(' · ')}</small>` : ''}</span><span class="pf-person-go">View ↗</span></button>`).join('')}</div>`}`;
}
async function openPerson(id, back = 'team') {
  if (back === 'profile' && !pfLeaveOk()) return;
  try { PF.person = await api('/profile/people/' + id); PF.personBack = back; PF.dirty = false; state.page = 'person'; render(); window.scrollTo(0, 0); } catch (e) { toast(e.message); }
}
function personPage() {
  const p = PF.person; if (!state.me) return loginPage(); if (!p) return dashboard();
  const block = b => `<section class="card pf-card"><h3>${esc(b.title)}</h3>${b.kind === 'text' ? `<p class="pf-about">${esc(b.text)}</p>` : b.kind === 'tags' ? `<div class="pf-tags">${b.tags.map(t => `<span class="tag">${esc(t)}</span>`).join('')}</div>` : `<div class="pf-list">${b.items.map(i => `<div class="pf-entry ${i.expired ? 'expired' : ''}"><div class="pf-entry-main"><div class="pf-entry-title">${esc(i.title)}${i.tag ? ` <span class="tag">${esc(i.tag)}</span>` : ''}${i.expired ? ' <span class="pill rejected">Expired</span>' : ''}</div>${i.sub ? `<div class="sub">${esc(i.sub)}</div>` : ''}${i.text ? `<p class="pf-entry-text">${esc(i.text)}</p>` : ''}${i.link ? `<a class="pf-link" href="${esc(i.link)}" target="_blank" rel="noopener noreferrer">${esc(i.link)}</a>` : ''}</div><div class="pf-entry-side">${i.meta ? `<span class="pf-meta">${esc(i.meta)}</span>` : ''}</div></div>`).join('')}</div>`}</section>`;
  return `<div class="pf pf-person-page">${PF.personBack === 'profile' ? `<button class="linkish pf-backlink" onclick="openProfile()">← Back to my profile</button>` : `<button class="linkish pf-backlink" onclick="state.tab='team';openDashboard()">← Back to team profiles</button>`}<div class="pf-head"><div class="pf-id">${personAvatar(p, 'large')}<div><div class="overline">Team profile</div><h2>${esc(p.name)}</h2><p class="sub">${esc([p.designation, p.department].filter(Boolean).join(' · '))}</p><div class="pf-tags">${p.research_roles.map(r => `<span class="tag">${esc(r)}</span>`).join('')}${p.languages.length ? `<span class="muted">Speaks ${p.languages.map(esc).join(', ')}</span>` : ''}</div></div></div><div class="pf-shared muted">${p.shared_orgs.length ? `You both work with ${p.shared_orgs.map(esc).join(', ')}.` : 'This is how your team sees your profile.'}<br>Read-only professional view.</div></div>${p.blocks.length ? p.blocks.map(block).join('') : '<div class="card"><p class="sub">This person has not shared any profile sections yet.</p></div>'}</div>`;
}
