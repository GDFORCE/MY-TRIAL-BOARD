// Name autocomplete with address autofill.
// Sources: the MTB hospital directory (when a search function is given) and
// Google Places API (New) when MTB_GOOGLE_MAPS_KEY is configured on the server.
window.MTBPlaces = (() => {
  let ready = null, places = null, keyRejected = false, apiWarned = false;
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  window.gm_authFailure = () => { keyRejected = true; toast?.('Google Maps rejected the API key. Check the key and its allowed websites.'); };

  function load(key) {
    if (!key) return Promise.resolve(null);
    if (ready) return ready;
    ready = new Promise((resolve, reject) => {
      window.__mtbMapsReady = resolve;
      const s = document.createElement('script');
      s.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(key)}&loading=async&libraries=places&v=weekly&callback=__mtbMapsReady`;
      s.async = true;
      s.onerror = () => reject(new Error('Google Maps could not be loaded'));
      document.head.append(s);
    }).then(() => google.maps.importLibrary('places')).then(lib => (places = lib)).catch(err => { console.warn(err); return null; });
    return ready;
  }

  // Turn a Places (New) result into MTB address fields.
  function toFields(p) {
    const parts = p.addressComponents || [];
    const get = (...types) => { for (const t of types) { const c = parts.find(x => x.types.includes(t)); if (c) return c.longText; } return ''; };
    const city = get('locality', 'postal_town', 'administrative_area_level_3', 'administrative_area_level_2');
    const state = get('administrative_area_level_1'), country = get('country'), pin = get('postal_code');
    let line1 = [get('premise', 'subpremise'), [get('street_number'), get('route')].filter(Boolean).join(' ')].filter(Boolean).join(', ');
    const line2 = [get('sublocality_level_2'), get('sublocality_level_1', 'neighborhood')].filter(Boolean).join(', ');
    if (!line1 && p.formattedAddress) {
      // Fall back to the leading part of the formatted address, minus the area/city/state/PIN tail.
      const drop = [city, state, country, line2, p.displayName].filter(Boolean).map(x => x.toLowerCase());
      line1 = p.formattedAddress.split(',').map(s => s.trim())
        .filter(s => s && !drop.some(d => s.toLowerCase().includes(d)) && !(pin && s.includes(pin)))
        .slice(0, 2).join(', ');
    }
    return {
      name: p.displayName || '', address1: line1 || line2, address2: line1 ? line2 : '', city, state, country, pin,
      phone: p.internationalPhoneNumber || p.nationalPhoneNumber || '', website: p.websiteURI || '',
      placeId: p.id || '',
    };
  }

  /**
   * attach(input, {primaryTypes, directory, onPick})
   *  directory(q) -> Promise<[{label, sub, badge, fields}]>   (optional, MTB records first)
   *  onPick(fields, source)                                     fills the form
   */
  function attach(input, opts) {
    if (!input || input.dataset.placesBound) return;
    input.dataset.placesBound = '1';
    input.setAttribute('autocomplete', 'off');
    input.setAttribute('role', 'combobox');
    input.setAttribute('aria-autocomplete', 'list');
    const wrap = input.closest('.field');
    const list = document.createElement('div');
    list.className = 'ac-list hidden';
    list.setAttribute('role', 'listbox');
    wrap.append(list);
    let items = [], active = -1, timer = null, seq = 0, token = null;

    const close = () => { list.classList.add('hidden'); input.setAttribute('aria-expanded', 'false'); active = -1; };
    const paint = (status = '') => {
      if (!items.length && !status) return close();
      const groups = [['mtb', 'Already on My Trial Board'], ['google', 'Suggestions from Google']];
      list.innerHTML = groups.map(([src, title]) => {
        const rows = items.map((it, i) => [it, i]).filter(([it]) => it.source === src);
        return rows.length ? `<div class="ac-group">${title}</div>` + rows.map(([it, i]) =>
          `<div class="ac-item ${i === active ? 'active' : ''}" role="option" data-i="${i}"><div><b>${esc(it.label)}</b><small>${esc(it.sub)}</small></div>${it.badge ? `<span class="ac-badge">${esc(it.badge)}</span>` : ''}</div>`).join('') : '';
      }).join('') + (status ? `<div class="ac-status">${esc(status)}</div>` : '') +
        (items.some(i => i.source === 'google') ? '<div class="ac-foot">Powered by Google</div>' : '');
      list.classList.remove('hidden');
      input.setAttribute('aria-expanded', 'true');
    };

    async function search(q) {
      const mine = ++seq;
      const jobs = [];
      if (opts.directory) jobs.push(opts.directory(q).then(r => r.map(x => ({ ...x, source: 'mtb' }))).catch(() => []));
      const lib = await load(state.mapsKey);
      if (lib && !keyRejected) {
        token ||= new lib.AutocompleteSessionToken();
        const req = { input: q, sessionToken: token };
        const types = typeof opts.primaryTypes === 'function' ? opts.primaryTypes() : opts.primaryTypes;
        if (types) req.includedPrimaryTypes = types;
        jobs.push(lib.AutocompleteSuggestion.fetchAutocompleteSuggestions(req)
          .then(({ suggestions }) => suggestions.filter(s => s.placePrediction).slice(0, 5).map(s => ({
            source: 'google', label: s.placePrediction.mainText?.toString() || s.placePrediction.text.toString(),
            sub: s.placePrediction.secondaryText?.toString() || '', prediction: s.placePrediction,
          })))
          .catch(err => {
            console.warn('Places autocomplete failed:', err);
            if (!apiWarned) { apiWarned = true; toast('Google suggestions are unavailable. Enable "Places API (New)" for this key.'); }
            return [];
          }));
      }
      const results = (await Promise.all(jobs)).flat();
      if (mine !== seq) return; // a newer search started
      if (document.activeElement !== input) return; // user already moved on; don't cover other fields
      items = results; active = -1;
      paint(results.length ? '' : (state.mapsKey ? 'No matches. Keep typing or fill the address manually.' : ''));
    }

    async function pick(i) {
      const it = items[i];
      if (!it) return;
      close();
      if (it.source === 'mtb') { opts.onPick(it.fields, 'mtb'); return; }
      input.classList.add('ac-loading');
      try {
        const place = it.prediction.toPlace();
        await place.fetchFields({ fields: ['displayName', 'formattedAddress', 'addressComponents', 'nationalPhoneNumber', 'internationalPhoneNumber', 'websiteURI'] });
        opts.onPick(toFields(place), 'google');
      } catch (err) {
        console.warn(err);
        toast('Could not load the address for that place. Please fill it manually.');
      } finally {
        input.classList.remove('ac-loading');
        token = null; // a session ends when a place is picked
      }
    }

    input.addEventListener('input', () => {
      clearTimeout(timer);
      if (input.dataset.autofilling) return; // value set by fill(), not typed: don't reopen suggestions
      const q = input.value.trim();
      if (q.length < 3) { items = []; return close(); }
      timer = setTimeout(() => search(q), 250);
    });
    input.addEventListener('keydown', e => {
      if (list.classList.contains('hidden') || !items.length) return;
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        active = (active + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
        paint();
      } else if (e.key === 'Enter' && active >= 0) { e.preventDefault(); pick(active); }
      else if (e.key === 'Escape') close();
    });
    list.addEventListener('mousedown', e => {
      const row = e.target.closest('.ac-item');
      if (row) { e.preventDefault(); pick(Number(row.dataset.i)); }
    });
    input.addEventListener('blur', () => setTimeout(close, 150));
  }

  // Fill inputs by id and flash them so the user sees what changed.
  function fill(map) {
    for (const [id, value] of Object.entries(map)) {
      const el = document.getElementById(id);
      if (!el || value == null || value === '') continue;
      el.value = value;
      el.dataset.autofilling = '1';
      el.dispatchEvent(new Event('input', { bubbles: true }));
      delete el.dataset.autofilling;
      el.classList.remove('autofilled'); void el.offsetWidth; el.classList.add('autofilled');
    }
  }

  return { load, attach, fill };
})();
