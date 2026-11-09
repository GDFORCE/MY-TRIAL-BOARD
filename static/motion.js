// Motion layer: page entrances, scroll reveals, hover effects, count-up metrics.
// Wraps app.js's render() without changing any app logic.
(() => {
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const root = document.getElementById('app');
  const bar = document.getElementById('scrollProgress');

  // Elements that rise in, one after another, when a new page opens.
  const TAB_SEL = [
    '.dash-body > :not(.dash-top):not(.metrics):not(.two-panel)',
    '.two-panel > *',
    '.table-wrap tbody tr',
  ].join(',');
  const MAIN_SEL = [
    '.auth-main > :not(form):not(.card):not(.two-panel)',
    '.auth-main form > :not(.form-grid)', '.form-grid > *',
    '.auth-card > :not(form)',
    '.sidebar > *', '.dash-top', '.metrics > *',
    TAB_SEL,
  ].join(',');
  const PAGE_SEL = ['.hero-copy > :not(h1)', '.auth-aside > :not(.stack):not(.three-mount)', '.stack-row', MAIN_SEL].join(',');

  function stagger(selector) {
    root.querySelectorAll(selector).forEach((el, i) => {
      el.style.setProperty('--i', Math.min(i, 18));
      el.setAttribute('data-stagger', '');
    });
  }
  // Drop the entrance attribute once it finishes so hover transforms work again.
  document.addEventListener('animationend', e => {
    if (e.animationName === 'rise' && e.target.hasAttribute('data-stagger')) e.target.removeAttribute('data-stagger');
  });

  function countUp() {
    root.querySelectorAll('.metric b').forEach(b => {
      const target = parseInt(b.textContent, 10);
      if (!(target > 0)) return;
      const start = performance.now(), dur = 1100;
      b.textContent = '0';
      const tick = now => {
        const p = Math.min((now - start) / dur, 1);
        b.textContent = Math.round(target * (1 - Math.pow(1 - p, 3)));
        if (p < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });
  }

  let observer;
  function setupReveal() {
    if (!('IntersectionObserver' in window)) return;
    observer?.disconnect();
    observer = new IntersectionObserver(entries => entries.forEach(e => {
      if (!e.isIntersecting) return;
      e.target.classList.add('in');
      observer.unobserve(e.target);
      setTimeout(() => e.target.classList.remove('reveal', 'in'), 1400);
    }), { threshold: 0.15, rootMargin: '0px 0px -40px 0px' });
    const groups = [['#features > :not(.features)'], ['.features > .feature'], ['.cta-band']];
    groups.forEach(([sel]) => root.querySelectorAll(sel).forEach((el, i) => {
      el.style.setProperty('--i', i);
      el.classList.add('reveal');
      observer.observe(el);
    }));
  }

  function onScroll() {
    const h = document.documentElement, max = h.scrollHeight - h.clientHeight;
    if (bar) bar.style.transform = `scaleX(${max > 0 ? h.scrollTop / max : 0})`;
    document.querySelector('.nav')?.classList.toggle('scrolled', h.scrollTop > 10);
  }
  addEventListener('scroll', onScroll, { passive: true });
  addEventListener('resize', onScroll, { passive: true });

  let lastKey = null, lastTab = null, lastPage = null;
  function afterRender() {
    const key = [state.page, state.step, state.me ? 1 : 0, state.org].join('|');
    const pageChanged = key !== lastKey;
    const onlyStep = pageChanged && state.page === lastPage && state.page === 'register';
    const tabChanged = !pageChanged && state.page === 'dashboard' && state.tab !== lastTab;
    lastKey = key; lastTab = state.tab; lastPage = state.page;
    root.classList.toggle('page-enter', pageChanged && !reduce);
    if (!reduce) {
      if (onlyStep) stagger(MAIN_SEL); // keep the side panel still between form steps
      else if (pageChanged) { stagger(PAGE_SEL); countUp(); setupReveal(); }
      else if (tabChanged) stagger(TAB_SEL);
    }
    onScroll();
  }

  const baseRender = window.render;
  window.render = function () { baseRender(); afterRender(); };
  if (root.children.length) afterRender(); // in case app.js rendered before this loaded

  // Cursor spotlight on feature cards, hero glow and 3D tilt on the hero preview.
  let tilted = null;
  document.addEventListener('pointermove', e => {
    const card = e.target.closest?.('.feature');
    if (card) {
      const r = card.getBoundingClientRect();
      card.style.setProperty('--mx', e.clientX - r.left + 'px');
      card.style.setProperty('--my', e.clientY - r.top + 'px');
    }
    if (reduce || e.pointerType !== 'mouse') return;
    const hero = e.target.closest?.('.hero');
    const display = hero?.querySelector('.hero-display');
    if (hero) {
      const r = hero.getBoundingClientRect();
      hero.style.setProperty('--hx', e.clientX - r.left + 'px');
      hero.style.setProperty('--hy', e.clientY - r.top + 'px');
    }
    if (display) {
      const d = display.getBoundingClientRect();
      const x = Math.max(-1, Math.min(1, (e.clientX - (d.left + d.width / 2)) / d.width));
      const y = Math.max(-1, Math.min(1, (e.clientY - (d.top + d.height / 2)) / d.height));
      display.style.setProperty('--ry', (x * 9).toFixed(2) + 'deg');
      display.style.setProperty('--rx', (-y * 9).toFixed(2) + 'deg');
      tilted = display;
    } else if (tilted) {
      tilted.style.setProperty('--rx', '0deg');
      tilted.style.setProperty('--ry', '0deg');
      tilted = null;
    }
  }, { passive: true });

  // Ripple on button press.
  document.addEventListener('pointerdown', e => {
    const btn = e.target.closest?.('.btn');
    if (!btn || btn.disabled || reduce) return;
    const r = btn.getBoundingClientRect(), size = Math.max(r.width, r.height) * 2.2;
    const dot = document.createElement('span');
    dot.className = 'ripple';
    dot.style.cssText = `width:${size}px;height:${size}px;left:${e.clientX - r.left - size / 2}px;top:${e.clientY - r.top - size / 2}px`;
    btn.appendChild(dot);
    setTimeout(() => dot.remove(), 700);
  });
})();
