/* Muse Life Graph - the app. One page, hash routes, plain DOM. */
'use strict';
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const ic = (n, cls = '') => `<svg class="icon ${cls}"><use href="#i-${n}"/></svg>`;
const enc = encodeURIComponent;
const photo = sha => `/api/photo/${enc(sha)}`;
const ref = pid => `/api/ref/${enc(pid)}`;
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const PRECISE = new Set(['exif', 'container', 'filename', 'recorded']);
let OV = null;            // overview
let LIST = [];            // moments the viewer can step through
let lastAnswer = null;

async function api(path, body, method) {
  const r = await fetch(path, body !== undefined || method ? {method: method || 'POST', headers: {'Content-Type': 'application/json'},
                                                               body: JSON.stringify(body ?? {})} : {});
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

function when(date, source, short) {
  if (!date) return 'undated';
  const [y, m, d] = date.split('-');
  if (source && !PRECISE.has(source)) return `around ${y}`;
  if (!m) return y;
  return short ? `${MONTHS[+m - 1]} ${y}` : `${MONTHS[+m - 1]} ${+d}, ${y}`;
}
function memWhen(x) {
  if (!x.precise) return x.date.slice(0, 4) === x.end.slice(0, 4) ? `around ${x.date.slice(0, 4)}` : `${x.date.slice(0, 4)}–${x.end.slice(0, 4)}`;
  return when(x.date, 'exif');
}
const initials = n => (n || '?').split(/\s+/).map(w => w[0]).join('').slice(0, 2).toUpperCase();
function avatar(p, cls = '') {
  return `<img class="${cls}" src="${ref(p.id)}" alt="${esc(p.name)}" title="${esc(p.name)}" loading="lazy" data-name="${esc(p.name)}">`;
}
// a person without a reference picture gets their initials instead of a broken image
document.addEventListener('error', e => {
  const img = e.target;
  if (img.tagName !== 'IMG' || !img.dataset.name || img.dataset.failed) return;
  img.dataset.failed = 1;
  const c = document.createElement('canvas'); c.width = c.height = 96;
  const g = c.getContext('2d'); g.fillStyle = '#e8d9cc'; g.fillRect(0, 0, 96, 96);
  g.fillStyle = '#8a5a3c'; g.font = '600 38px Inter, sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle';
  g.fillText(initials(img.dataset.name), 48, 50); img.src = c.toDataURL();
}, true);

function toast(text, undo) {
  $('.toast')?.remove();
  const t = document.createElement('div');
  t.className = 'toast'; t.innerHTML = `<span>${esc(text)}</span>${undo ? '<button>Undo</button>' : ''}`;
  if (undo) t.querySelector('button').onclick = async () => { t.remove(); await undo(); };
  document.body.append(t);
  setTimeout(() => t.remove(), 9000);
}

/* ---------------- shell ---------------- */
const NAV = [
  ['', 'home', 'Home'], ['memories', 'memories', 'Memories'], ['timeline', 'timeline', 'Timeline'],
  ['people', 'people', 'People'], ['connections', 'graph', 'Connections'], ['films', 'film', 'Films'],
  ['faces', 'face', 'Who is this?'],
];
const TABS = [['', 'home', 'Home'], ['memories', 'memories', 'Memories'], ['people', 'people', 'People'],
              ['films', 'film', 'Films'], ['faces', 'face', 'Faces']];
function shell(route) {
  const n = OV ? OV.unknown_faces : 0;
  const b = (r) => r === 'faces' && n ? `<span class="badge">${n > 999 ? '999+' : n}</span>` : '';
  $('#nav').innerHTML = NAV.map(([r, i, l]) => `<a href="#/${r}" class="${route === r ? 'on' : ''}">${ic(i)}${l}${b(r)}</a>`).join('');
  $('#tabbar').innerHTML = TABS.map(([r, i, l]) => `<a href="#/${r}" class="${route === r ? 'on' : ''}">${ic(i)}${l}${b(r)}</a>`).join('');
  $$('.rail .nav a[href="#/add"]').forEach(a => a.classList.toggle('on', route === 'add'));
}
addEventListener('scroll', () => $('#topbar').classList.toggle('scrolled', scrollY > 4), {passive: true});
$('#theme').onclick = () => {
  const dark = matchMedia('(prefers-color-scheme: dark)').matches;
  const cur = document.documentElement.dataset.theme || (dark ? 'dark' : 'light');
  const next = cur === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem('theme', next); } catch (e) { /* private mode */ }
};
try { const t = localStorage.getItem('theme'); if (t) document.documentElement.dataset.theme = t; } catch (e) { /* ignore */ }
$('#searchform').onsubmit = e => { e.preventDefault(); const q = $('#q').value.trim(); if (q) location.hash = `#/search?q=${enc(q)}`; };
addEventListener('keydown', e => {
  if (e.key === '/' && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) { e.preventDefault(); $('#q').focus(); }
});

/* ---------------- router ---------------- */
const ROUTES = {
  '': home, memories, memory, timeline, year: yearPage, people, person, connections, films, film: filmPage,
  faces, add: addPage, search: searchPage,
};
let navToken = 0;
async function route() {
  const h = location.hash.replace(/^#\/?/, '');
  const [path, qs] = h.split('?');
  const [name, ...rest] = path.split('/');
  const arg = rest.map(decodeURIComponent).join('/');
  const params = new URLSearchParams(qs || '');
  const token = ++navToken;
  closeViewer();
  if (!OV || name === '') OV = await api('/api/overview').catch(() => OV);
  if (token !== navToken) return;
  if (OV && !OV.photos && !OV.videos && name !== 'add') return welcome();
  shell(name);
  const page = $('#page');
  page.innerHTML = '<div class="skeleton" style="height:220px"></div>';
  window.scrollTo(0, 0);
  try {
    const fn = ROUTES[name] || home;
    const html = await fn(arg, params);
    if (token !== navToken) return;
    if (html !== undefined) { page.innerHTML = `<div class="fade-in">${html}</div>`; }
    afterRender[name]?.(arg, params);
  } catch (err) {
    page.innerHTML = `<div class="empty"><h2>Something went wrong</h2><p>${esc(err.message)}</p></div>`;
  }
  if (name !== 'search') $('#q').value = '';
}
const afterRender = {};
addEventListener('hashchange', route);

// moments shown on the current page, so the viewer can step through them
function photosHtml(cards, opts = {}) {
  LIST = cards.map(c => c.id);
  return `<div class="photos">${cards.map(c => `<div class="photo" data-m="${esc(c.id)}">
      <img src="${photo(c.sha)}" alt="${esc(c.summary || '')}" loading="lazy" ${c.w && c.h ? `width="${c.w}" height="${c.h}"` : ''}>
      ${c.kind === 'video' ? `<div class="play"><span>${ic('play')}</span></div>` : ''}
      ${opts.why && c.why ? `<div class="why">${esc(c.why)}</div>` : ''}</div>`).join('')}</div>`;
}
document.addEventListener('click', e => {
  const ph = e.target.closest('[data-m]');
  if (ph && !e.target.closest('.viewer')) { openViewer(ph.dataset.m); }
});

function memCard(x) {
  return `<a class="mem" href="#/memory/${enc(x.id)}">
    <div class="pic"><img src="${photo(x.cover)}" alt="" loading="lazy">
      <span class="count">${x.count > x.videos ? `${ic('memories')}${x.count - x.videos}` : ''}${x.count > x.videos && x.videos ? ' · ' : ''}${x.videos ? `${ic('play')}${x.videos}` : ''}</span></div>
    <div class="meta"><span>${esc(memWhen(x))}</span><span class="avatars">${x.people.slice(0, 4).map(p => avatar(p)).join('')}</span></div>
    <h3 dir="auto">${esc(x.title)}</h3>
    <p class="line" dir="auto">${esc(x.line || '')}</p></a>`;
}

/* ---------------- welcome / import ---------------- */
function welcome() {
  shell('add');
  $('#page').innerHTML = `<div class="welcome fade-in">
    <div>
      <div class="eyebrow">Muse Life Graph</div>
      <h1>Your photos already<br>tell your story.</h1>
      <p class="lead">Point Muse at your pictures and videos. It sees who is in them, when and where they happened and
        what was said, builds the map of your life, and turns any moment into a film you'd actually send.</p>
      ${sourcesHtml()}
      <p class="small faint" style="margin-top:22px">Your photos stay on this computer. Muse looks at each one once; nothing is posted anywhere.</p>
    </div>
    <div class="collage" aria-hidden="true">
      <div style="left:8%;top:6%;width:56%;height:56%;transform:rotate(-5deg)"><i style="background:linear-gradient(135deg,#f2b880,#e0592a)"></i></div>
      <div style="right:4%;top:20%;width:46%;height:46%;transform:rotate(6deg)"><i style="background:linear-gradient(135deg,#c7a3cf,#6d4c74)"></i></div>
      <div style="left:22%;bottom:2%;width:50%;height:44%;transform:rotate(2deg)"><i style="background:linear-gradient(135deg,#8fc7a8,#2f7d5b)"></i></div>
    </div></div>`;
  bindSources();
}
function sourcesHtml() {
  return `<div class="sources">
    <button class="card source" id="src-folder"><span class="ic">${ic('folder')}</span>
      <span><b>Choose a folder</b><br><span class="small muted">Photos and videos on this computer or a drive. They stay where they are.</span></span>
      <span class="btn sm">Choose</span></button>
    <button class="card source" id="src-meta"><span class="ic">${ic('meta')}</span>
      <span><b>Facebook or Instagram</b><br><span class="small muted">Your downloaded copy (.zip): photos, videos, captions, places and dates.</span></span>
      <span class="btn sm">Import</span></button></div>`;
}
function bindSources() {
  $('#src-folder')?.addEventListener('click', async () => {
    toast('A folder window opened on your computer…');
    try { const r = await api('/api/import/folder', {}); if (!r.cancelled) location.hash = '#/add'; route(); }
    catch (e) { toast(e.message); }
  });
  $('#src-meta')?.addEventListener('click', () => metaModal());
}
function metaModal() {
  const bg = document.createElement('div');
  bg.className = 'modal-bg';
  bg.innerHTML = `<div class="card modal"><h2>Import from Facebook or Instagram</h2>
    <p class="muted">Meta lets you download a copy of everything you posted. Muse reads that copy, not your account.</p>
    <div class="steps" style="margin:18px 0">
      <div class="step"><span class="dot">1</span><div>Open <a href="https://accountscenter.facebook.com/info_and_permissions/dyi/" target="_blank" rel="noopener">Accounts Center → Download your information</a>.</div></div>
      <div class="step"><span class="dot">2</span><div>Choose Facebook and/or Instagram, <b>Photos and videos</b> + <b>Posts</b>, all time. Format: HTML or JSON, high quality.</div></div>
      <div class="step"><span class="dot">3</span><div>When Meta emails you, download the .zip files and choose them here. Albums, captions, places and dates come along.</div></div>
    </div>
    <div class="chips" style="justify-content:flex-end"><button class="btn ghost" data-x>Cancel</button>
      <button class="btn primary" data-go>${ic('meta')}Choose the .zip files</button></div></div>`;
  document.body.append(bg);
  bg.onclick = async e => {
    if (e.target === bg || e.target.closest('[data-x]')) return bg.remove();
    if (e.target.closest('[data-go]')) {
      bg.remove(); toast('A file window opened on your computer…');
      try { const r = await api('/api/import/meta', {}); if (!r.cancelled) { location.hash = '#/add'; route(); } }
      catch (err) { toast(err.message); }
    }
  };
}

let importTimer = null;
async function addPage() {
  const st = await api('/api/import');
  const w = st.waiting;
  const pct = st.total ? Math.round(100 * st.done / st.total) : 0;
  const stepCls = s => {
    const order = ['finding', 'ready', 'looking', 'done'];
    const cur = st.state === 'unpacking' ? 'finding' : st.state;
    const i = order.indexOf(cur), j = order.indexOf(s);
    return i > j ? 'done' : i === j ? 'now' : '';
  };
  let body = '';
  if (['finding', 'unpacking'].includes(st.state)) {
    body = `<h3>${st.state === 'unpacking' ? 'Unpacking your export' : 'Finding your photos and videos'}</h3>
      <p class="muted small">${esc(st.source || '')}</p><div class="progress"><i style="width:${pct}%"></i></div>
      <p class="small muted">${st.done || 0} of ${st.total || '…'} files · fingerprinting each one so copies (WhatsApp, re-saves, bursts) are counted once</p>`;
  } else if (st.state === 'looking') {
    body = `<h3>Muse is looking at your pictures</h3><div class="progress"><i style="width:${pct}%"></i></div>
      <p class="small muted">${st.done} of ${st.total} · who is in each one, when and where it happened, what was said${st.failed ? ` · ${st.failed} could not be read` : ''}</p>
      <p class="small faint">You can keep using the app; new memories appear as they are ready.</p>`;
  } else if (w.items) {
    body = `<h3>${w.items} new ${w.items === 1 ? 'item is' : 'items are'} ready for Muse</h3>
      <p class="muted">${w.by_kind.photo} photos · ${w.by_kind.video} videos · ${w.by_kind.audio} voice notes${st.duplicates ? ` · ${st.duplicates} copies set aside` : ''}</p>
      <p class="small muted">Muse looks at each one once: about <b>$${w.dollars.toFixed(2)}</b> and <b>${Math.max(1, Math.round(w.minutes))} min</b>.</p>
      <div class="chips" style="margin-top:12px"><button class="btn primary" id="look">${ic('sparkle')}Let Muse look</button>
      ${w.items > 50 ? `<button class="btn" id="look50">Try 50 first</button>` : ''}</div>`;
  } else if (st.state === 'done') {
    body = `<h3>${ic('check')} Done</h3><p class="muted">Your new memories are ready.</p>
      <div class="chips"><a class="btn primary" href="#/memories">See memories</a><a class="btn" href="#/faces">Name the faces Muse found</a></div>`;
  } else if (st.state === 'failed') {
    body = `<h3>That didn't work</h3><p class="muted">${esc(st.error)}</p>`;
  } else {
    body = `<p class="muted">Choose where your photos are. You can add more sources any time.</p>`;
  }
  clearTimeout(importTimer);
  if (['finding', 'unpacking', 'looking'].includes(st.state)) importTimer = setTimeout(() => { if (location.hash.startsWith('#/add')) refreshAdd(); }, 1500);
  return `<div class="phead"><div><div class="eyebrow">Add photos</div><h1>Bring your life in</h1>
      <p>From a folder or from what you shared on Facebook and Instagram. Copies are found and set aside; your files are never moved or changed.</p></div></div>
    <div class="two"><div class="card pad" id="importbox">${body}</div>
      <div class="side"><div class="card pad"><div class="steps">
        <div class="step ${stepCls('finding')}"><span class="dot">1</span><div><b>Find</b><div class="small muted">every photo, video and voice note</div></div></div>
        <div class="step ${stepCls('ready')}"><span class="dot">2</span><div><b>Check</b><div class="small muted">copies set aside, cost shown before anything is spent</div></div></div>
        <div class="step ${stepCls('looking')}"><span class="dot">3</span><div><b>Muse looks</b><div class="small muted">people, dates, places, words, feelings</div></div></div>
        <div class="step ${stepCls('done')}"><span class="dot">4</span><div><b>Your graph</b><div class="small muted">memories, people, connections, films</div></div></div>
      </div></div></div></div>
    <div class="section"><div class="section-head"><h2>Add a source</h2></div>${sourcesHtml()}</div>`;
}
async function refreshAdd() {
  const html = await addPage();
  const box = new DOMParser().parseFromString(html, 'text/html');
  $('#importbox').innerHTML = box.querySelector('#importbox').innerHTML;
  $('.side').innerHTML = box.querySelector('.side').innerHTML;
  afterRender.add();
}
afterRender.add = () => {
  bindSources();
  const go = async (limit) => {
    try { await api(`/api/import/look${limit ? `?limit=${limit}` : ''}`, {}); refreshAdd(); } catch (e) { toast(e.message); }
  };
  $('#look')?.addEventListener('click', () => go());
  $('#look50')?.addEventListener('click', () => go(50));
};

/* ---------------- home ---------------- */
function greeting() {
  const h = new Date().getHours();
  return h < 5 ? 'Good night' : h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
}
async function home() {
  const o = OV;
  const hero = o.on_this_day[0] || o.recent.find(x => x.people.length) || o.recent[0];
  const heroLabel = o.on_this_day[0] ? `On this day · ${hero.years_ago} year${hero.years_ago > 1 ? 's' : ''} ago` : 'A memory';
  const asks = [`When was I happiest?`, `Photos of me as a child`, o.recent[1] ? `Tell me about ${o.recent[1].title}` : 'Who do I spend the most time with?'];
  const faces = await api('/api/faces?limit=6').catch(() => ({faces: [], total: 0}));
  return `<div class="hello">
      <div class="intro">
        <div class="eyebrow">${greeting()}${o.owner ? `, ${esc(o.owner)}` : ''}</div>
        <h1>Here is your life,<br>as Muse sees it.</h1>
        <div class="stats"><span><b>${o.photos}</b> photos</span><span><b>${o.videos}</b> videos</span><span><b>${o.people}</b> people</span>
          <span><b>${o.memories}</b> memories</span>${o.years ? `<span><b>${o.years[0]}–${o.years[1]}</b></span>` : ''}</div>
        <form class="askbox" id="askform"><input id="askq" dir="auto" placeholder="Ask anything — “when did we go to the sea?”" aria-label="Ask about your life">
          <button class="btn primary">${ic('sparkle')}Ask</button></form>
        <div class="suggest">${asks.map(a => `<button class="chip" data-ask="${esc(a)}">${esc(a)}</button>`).join('')}</div>
      </div>
      ${hero ? `<a class="hero" href="#/memory/${enc(hero.id)}"><img src="${photo(hero.cover)}" alt="">
        <div class="cap"><div class="eyebrow">${esc(heroLabel)}</div><h3 dir="auto">${esc(hero.title)}</h3>
        <div class="small">${esc(memWhen(hero))}${hero.people.length ? ' · ' + hero.people.map(p => esc(p.name)).join(', ') : ''}</div></div></a>` : ''}
    </div>
    ${faces.total ? `<div class="section card needs">
      <div class="facestack">${faces.faces.slice(0, 5).map(f => `<img src="/api/crop/${enc(f.id)}" alt="" loading="lazy">`).join('')}</div>
      <div><h3>${faces.total} faces Muse couldn't name yet</h3><div class="small muted">Name a few — every film and search gets better, and Muse learns to recognise them next time.</div></div>
      <a class="btn primary" href="#/faces">Who is this? ${ic('arrow')}</a></div>` : ''}
    <div class="section"><div class="section-head"><div><h2>Recent memories</h2><p class="muted small">Moments that belong together, titled by Muse</p></div>
      <a class="btn ghost sm" href="#/memories">All memories ${ic('arrow')}</a></div>
      <div class="row-scroll">${o.recent.map(memCard).join('')}</div></div>
    <div class="section"><div class="section-head"><div><h2>Make a film</h2><p class="muted small">One sentence. A crew of Muse agents writes, cuts, watches and re-cuts it.</p></div></div>
      <div class="ideas">
        <button class="idea" data-film="birthday">${ic('cake')}<b>A birthday film</b><span class="small muted">For someone you love — with blessings from family and friends.</span></button>
        <button class="idea" data-film="together">${ic('together')}<b>The two of us</b><span class="small muted">Every moment two people shared, from the first photo to now.</span></button>
        <button class="idea" data-film="year">${ic('calendar')}<b>A year in a minute</b><span class="small muted">One year of your life, in the order it happened.</span></button>
      </div></div>`;
}
afterRender[''] = () => {
  $('#askform').onsubmit = e => { e.preventDefault(); const q = $('#askq').value.trim(); if (q) location.hash = `#/search?q=${enc(q)}`; };
  $$('[data-ask]').forEach(b => b.onclick = () => { location.hash = `#/search?q=${enc(b.dataset.ask)}`; });
  $$('[data-film]').forEach(b => b.onclick = () => { location.hash = `#/films?idea=${b.dataset.film}`; });
};

/* ---------------- memories ---------------- */
async function memories(_, params) {
  const all = await api('/api/memories');
  const years = [...new Set(all.map(x => x.date.slice(0, 4)))].sort().reverse();
  const y = params.get('year');
  const shown = y ? all.filter(x => x.date.startsWith(y)) : all;
  return `<div class="phead"><div><div class="eyebrow">Memories</div><h1>Moments that belong together</h1>
      <p>Muse groups the pictures of one day, one trip or one old album page, and names each memory from what it sees.</p></div></div>
    <div class="chips" style="margin-bottom:24px"><a class="chip ${y ? '' : 'on'}" href="#/memories">All</a>
      ${years.map(v => `<a class="chip ${v === y ? 'on' : ''}" href="#/memories?year=${v}">${v}</a>`).join('')}</div>
    ${shown.length ? `<div class="mgrid">${shown.map(memCard).join('')}</div>` : '<div class="empty">No memories yet.</div>'}`;
}
async function memory(key) {
  const m = await api(`/api/memory/${enc(key)}`);
  const people = m.people.map(p => `<a class="chip" href="#/person/${enc(p.id)}">${avatar(p)}${esc(p.name)}</a>`).join('');
  return `<a class="back" href="#/memories">${ic('back')}Memories</a>
    <div class="phead"><div><div class="eyebrow">${esc(memWhen(m))}${m.place ? ` · ${esc(m.place)}` : ''}</div>
      <h1 dir="auto">${esc(m.title)}</h1><p dir="auto">${esc(m.line || '')}</p>
      <div class="chips" style="margin-top:14px">${people}${m.mood.map(x => `<span class="chip accent">${esc(x)}</span>`).join('')}</div></div>
      <button class="btn primary" id="memfilm" data-title="${esc(m.title)}" data-when="${esc(memWhen(m))}">${ic('film')}Make a film from this</button></div>
    ${photosHtml(m.moments)}`;
}
afterRender.memory = () => {
  const b = $('#memfilm');
  if (b) b.onclick = () => { location.hash = `#/films?req=${enc(`A 45-second film of “${b.dataset.title}” (${b.dataset.when}), warm and simple.`)}`; };
};

/* ---------------- timeline ---------------- */
async function timeline() {
  const ys = await api('/api/timeline');
  const byDecade = {};
  ys.forEach(y => (byDecade[y.year.slice(0, 3) + '0s'] ??= []).push(y));
  return `<div class="phead"><div><div class="eyebrow">Timeline</div><h1>Year by year</h1>
      <p>Dates come from the camera when it kept them, otherwise Muse reads them from the picture itself — clothes, cars, film grain — and says “around”.</p></div></div>
    ${Object.entries(byDecade).reverse().map(([d, list]) => `<div class="decade">${d}</div><div class="years">${list.reverse().map(y => `
      <a class="year" href="#/year/${y.year}"><img src="${photo(y.cover)}" alt="" loading="lazy">
        <div class="cap"><b>${y.year}</b><span>${y.count} ${y.count === 1 ? 'moment' : 'moments'}${y.people.length ? ' · ' + esc(y.people.slice(0, 2).join(', ')) : ''}</span></div></a>`).join('')}</div>`).join('')}`;
}
async function yearPage(y) {
  const d = await api(`/api/year/${enc(y)}`);
  return `<a class="back" href="#/timeline">${ic('back')}Timeline</a>
    <div class="phead"><div><div class="eyebrow">${d.memories.length} memories</div><h1>${esc(y)}</h1></div>
      <a class="btn primary" href="#/films?req=${enc(`A one-minute film of my year ${y}, in the order it happened.`)}">${ic('film')}This year in a minute</a></div>
    <div class="river">${d.memories.map(x => `<div class="stop"><div class="when">${esc(memWhen(x))}</div>
      <a href="#/memory/${enc(x.id)}" style="text-decoration:none"><h3 dir="auto" style="margin:4px 0 10px">${esc(x.title)}</h3></a>
      <div class="row-scroll" style="grid-auto-columns:minmax(150px,190px)">${x.shas.map(s => `<a class="mem" href="#/memory/${enc(x.id)}"><div class="pic"><img src="${photo(s)}" alt="" loading="lazy"></div></a>`).join('')}</div></div>`).join('')}</div>`;
}

/* ---------------- people ---------------- */
async function people() {
  const ps = await api('/api/persons');
  return `<div class="phead"><div><div class="eyebrow">People</div><h1>The people in your life</h1>
      <p>Everyone you have named. Muse recognises them in new pictures from the faces you confirmed — and asks when it isn't sure.</p></div>
      <a class="btn" href="#/faces">${ic('face')}Name more faces</a></div>
    <div class="pgrid">${ps.map(p => `<a class="pcard" href="#/person/${enc(p.id)}">
      ${avatar(p, 'portrait' + (p.owner ? ' owner-ring' : ''))}<b dir="auto">${esc(p.name)}</b>
      <span class="sub">${p.owner ? 'You · ' : ''}${p.count} ${p.count === 1 ? 'picture' : 'pictures'}${p.from ? ` · ${p.from}${p.to !== p.from ? '–' + p.to : ''}` : ''}</span></a>`).join('')}</div>`;
}
async function person(pid) {
  const p = await api(`/api/person/${enc(pid)}`);
  const max = Math.max(1, ...p.years.map(y => y[1]));
  const bars = p.years.length > 1 ? `<div class="card pad"><div class="label small faint">Pictures by year</div>
      <div class="bars" style="margin-top:10px">${p.years.map(([y, n]) => `<i style="height:${Math.max(8, 100 * n / max)}%" title="${y}: ${n}"></i>`).join('')}</div>
      <div class="small faint" style="display:flex;justify-content:space-between;margin-top:6px"><span>${p.years[0][0]}</span><span>${p.years.at(-1)[0]}</span></div></div>` : '';
  return `<a class="back" href="#/people">${ic('back')}People</a>
    <div class="phero">${avatar(p, 'portrait' + (p.owner ? ' owner-ring' : ''))}
      <div><div class="eyebrow">${p.owner ? 'You' : esc(p.relation || 'Person')}</div><h1 dir="auto">${esc(p.name)}</h1>
        <div class="statline"><div><b>${p.count}</b><span>pictures</span></div><div><b>${p.videos}</b><span>videos</span></div>
          ${p.years.length ? `<div><b>${p.years[0][0]}${p.years.length > 1 ? '–' + p.years.at(-1)[0] : ''}</b><span>years</span></div>` : ''}
          <div><b>${p.with.length}</b><span>people with</span></div></div>
        <div class="chips" style="margin-top:18px">
          <a class="btn primary sm" href="#/films?req=${enc(`A 60-second birthday film for ${p.name}, warm and a little funny.`)}">${ic('cake')}Birthday film</a>
          <a class="btn sm" href="#/search?q=${enc(`Tell me about ${p.name}`)}">${ic('sparkle')}Ask about ${esc(p.name.split(' ')[0])}</a>
          <button class="btn sm" id="bless" data-pid="${esc(p.id)}">${ic('mic')}Ask for blessings</button></div></div></div>
    <div class="two section"><div>
        ${p.memories.length ? `<div class="section-head" style="margin-top:0"><h2>Memories</h2></div><div class="row-scroll">${p.memories.map(memCard).join('')}</div>` : ''}
        <div class="section-head section"><h2>All pictures</h2></div>${photosHtml(p.moments)}</div>
      <div class="side">
        ${p.with.length ? `<div class="card pad"><div class="label small faint">Often with</div><div class="withlist" style="margin-top:8px">${p.with.map(w =>
          `<a href="#/person/${enc(w.id)}">${avatar(w)}<span dir="auto">${esc(w.name)}</span><span class="n">${w.count} together</span></a>`).join('')}</div>
          <a class="btn sm" style="margin-top:12px;width:100%" href="#/connections?focus=${enc(p.id)}">${ic('graph')}See connections</a></div>` : ''}
        ${bars}
        ${p.mood.length || p.places.length ? `<div class="card pad">${p.mood.length ? `<div class="label small faint">In their pictures</div><div class="chips" style="margin:8px 0 14px">${p.mood.map(x => `<span class="chip accent">${esc(x)}</span>`).join('')}</div>` : ''}
          ${p.places.length ? `<div class="label small faint">Places</div><div class="chips" style="margin-top:8px">${p.places.map(x => `<span class="chip">${ic('pin')}${esc(x)}</span>`).join('')}</div>` : ''}</div>` : ''}
      </div></div>`;
}
afterRender.person = () => {
  const b = $('#bless');
  if (b) b.onclick = async () => {
    const r = await api('/api/blessing_requests', {person_id: b.dataset.pid, message: ''});
    const url = location.origin + r.url;
    navigator.clipboard?.writeText(url).catch(() => {});
    toast('Blessing link copied — send it to family and friends');
  };
};

/* ---------------- connections ---------------- */
async function connections() {
  return `<div class="phead"><div><div class="eyebrow">Connections</div><h1>Who appears with whom</h1>
      <p>A line means two people are in the same pictures; thicker means more often. Click a person or a line.</p></div></div>
    <div class="graphwrap" id="gw"><svg id="gsvg"></svg><div class="glegend" id="glegend"></div></div>`;
}
afterRender.connections = async (_, params) => {
  const g = await api('/api/graph');
  const svg = $('#gsvg'), wrap = $('#gw');
  $('#glegend').innerHTML = `<span>${g.nodes.length} people · ${g.edges.length} connections · solid = same picture, dotted = same event</span>${g.unknown_faces ? `<a class="chip" href="#/faces">${g.unknown_faces} unnamed faces</a>` : ''}`;
  if (!g.nodes.length) { wrap.innerHTML = '<div class="empty"><h2>No people yet</h2><p><a href="#/faces">Name a few faces</a> and the map appears.</p></div>'; return; }
  const W = wrap.clientWidth, H = wrap.clientHeight;
  const maxC = Math.max(1, ...g.nodes.map(n => n.count)), maxW = Math.max(1, ...g.edges.map(e => e.w));
  const N = g.nodes.map((n, i) => ({...n, r: 22 + 26 * Math.sqrt(n.count / maxC),
    x: W / 2 + Math.cos(i * 2.4) * (60 + i * 18), y: H / 2 + Math.sin(i * 2.4) * (60 + i * 18), vx: 0, vy: 0}));
  const byId = Object.fromEntries(N.map(n => [n.id, n]));
  const E = g.edges.map(e => ({...e, s: byId[e.a], t: byId[e.b]})).filter(e => e.s && e.t);
  // a small force layout: springs on edges, repulsion between all, gentle pull to the centre
  for (let k = 0; k < 420; k++) {
    const cool = 1 - k / 420;
    for (let i = 0; i < N.length; i++) for (let j = i + 1; j < N.length; j++) {
      const a = N[i], b = N[j]; let dx = b.x - a.x, dy = b.y - a.y; const d2 = Math.max(80, dx * dx + dy * dy), d = Math.sqrt(d2);
      const f = 5200 / d2 + (d < a.r + b.r + 30 ? (a.r + b.r + 30 - d) * .5 : 0);
      dx /= d; dy /= d; a.vx -= dx * f; a.vy -= dy * f; b.vx += dx * f; b.vy += dy * f;
    }
    for (const e of E) {
      const dx = e.t.x - e.s.x, dy = e.t.y - e.s.y, d = Math.max(1, Math.hypot(dx, dy));
      const want = 150 - 60 * (e.w / maxW), f = (d - want) * .02 * (1 + e.w / maxW);
      e.s.vx += dx / d * f; e.s.vy += dy / d * f; e.t.vx -= dx / d * f; e.t.vy -= dy / d * f;
    }
    for (const n of N) {
      n.vx += (W / 2 - n.x) * .004; n.vy += (H / 2 - n.y) * .004;
      n.x += n.vx * cool; n.y += n.vy * cool; n.vx *= .6; n.vy *= .6;
    }
  }
  let view = {x: 0, y: 0, k: 1};
  const fit = () => {
    const xs = N.map(n => n.x), ys = N.map(n => n.y), pad = 90;
    const x0 = Math.min(...xs) - pad, x1 = Math.max(...xs) + pad, y0 = Math.min(...ys) - pad, y1 = Math.max(...ys) + pad;
    const k = Math.min(1.6, W / (x1 - x0), H / (y1 - y0));
    view = {k, x: W / 2 - k * (x0 + x1) / 2, y: H / 2 - k * (y0 + y1) / 2};
  };
  fit();
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.innerHTML = `<defs>${N.map((n, i) => `<clipPath id="c${i}"><circle r="${n.r}"/></clipPath>`).join('')}</defs><g id="gv">
    ${E.map((e, i) => `<line class="gedge" data-e="${i}" stroke-width="${2 + 8 * e.w / maxW}" ${e.pics ? '' : 'stroke-dasharray="2 7"'} x1="${e.s.x}" y1="${e.s.y}" x2="${e.t.x}" y2="${e.t.y}"><title>${esc(e.s.name)} & ${esc(e.t.name)}: ${linkText(e)}</title></line>`).join('')}
    ${N.map((n, i) => `<g class="gnode ${n.owner ? 'owner' : ''}" data-n="${i}" transform="translate(${n.x},${n.y})">
      <circle r="${n.r}" fill="var(--bg-2)"/><image href="${ref(n.id)}" x="${-n.r}" y="${-n.r}" width="${2 * n.r}" height="${2 * n.r}" clip-path="url(#c${i})" preserveAspectRatio="xMidYMid slice"/>
      <circle class="ring" r="${n.r}"/><text y="${n.r + 18}" text-anchor="middle">${esc(n.name)}</text></g>`).join('')}</g>`;
  const gv = $('#gv');
  const apply = () => gv.setAttribute('transform', `translate(${view.x},${view.y}) scale(${view.k})`);
  apply();
  const panel = html => { $('.gpanel')?.remove(); if (html) wrap.insertAdjacentHTML('beforeend', `<div class="card gpanel fade-in">${html}</div>`); };
  const focus = n => {
    const near = new Set([n.id, ...E.filter(e => e.s === n || e.t === n).flatMap(e => [e.s.id, e.t.id])]);
    $$('.gnode', svg).forEach(el => el.classList.toggle('dim', !near.has(N[+el.dataset.n].id)));
    $$('.gedge', svg).forEach(el => { const e = E[+el.dataset.e]; el.classList.toggle('dim', e.s !== n && e.t !== n); });
    const links = E.filter(e => e.s === n || e.t === n).sort((a, b) => b.w - a.w);
    panel(`<div style="display:flex;gap:12px;align-items:center">${avatar(n, 'portrait" style="width:64px;height:64px;border-width:2px')}
      <div><h3 dir="auto">${esc(n.name)}</h3><div class="small muted">${n.count} pictures${n.relation ? ' · ' + esc(n.relation) : ''}</div></div></div>
      <div class="withlist" style="margin:12px 0">${links.map(e => { const o = e.s === n ? e.t : e.s;
        return `<a href="#" data-pair="${esc(n.id)}|${esc(o.id)}">${avatar(o)}<span>${esc(o.name)}</span><span class="n">${linkText(e)}</span></a>`; }).join('') || '<span class="small muted">Not in a picture with anyone named yet.</span>'}</div>
      <a class="btn sm primary" href="#/person/${enc(n.id)}">Open ${esc(n.name.split(' ')[0])}'s page</a>`);
  };
  const pair = async (a, b) => {
    const ms = await api(`/api/shared?a=${enc(a)}&b=${enc(b)}`);
    const na = byId[a], nb = byId[b];
    const ed = E.find(x => (x.s === na && x.t === nb) || (x.s === nb && x.t === na));
    panel(`<h3>${esc(na.name)} & ${esc(nb.name)}</h3><div class="small muted" style="margin-bottom:10px">${ed ? linkText(ed) : ''}</div>
      ${photosHtml(ms.slice(0, 12)).replace('class="photos"', 'class="photos" style="columns:2"')}
      <a class="btn sm primary" style="margin-top:10px" href="#/films?req=${enc(`A one-minute film about ${na.name} and ${nb.name} together, from the first picture to the last.`)}">${ic('film')}Film of the two</a>`);
  };
  const clear = () => { $$('.dim', svg).forEach(el => el.classList.remove('dim')); panel(''); };
  wrap.addEventListener('click', e => {
    const p = e.target.closest('[data-pair]');
    if (p) { e.preventDefault(); const [a, b] = p.dataset.pair.split('|'); pair(a, b); }
  });
  // pan, zoom, click
  let drag = null, moved = false;
  svg.addEventListener('pointerdown', e => { drag = {x: e.clientX, y: e.clientY, vx: view.x, vy: view.y}; moved = false; svg.setPointerCapture(e.pointerId); svg.classList.add('drag'); });
  svg.addEventListener('pointermove', e => {
    if (!drag) return; const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (Math.abs(dx) + Math.abs(dy) > 4) moved = true;
    view.x = drag.vx + dx * W / svg.clientWidth; view.y = drag.vy + dy * H / svg.clientHeight; apply();
  });
  svg.addEventListener('pointerup', e => {
    svg.classList.remove('drag'); drag = null; if (moved) return;
    // pointer capture retargets the event to the svg; find what is really under the pointer
    const hit = document.elementFromPoint(e.clientX, e.clientY) || e.target;
    const n = hit.closest('.gnode'), l = hit.closest('.gedge');
    if (n) focus(N[+n.dataset.n]); else if (l) { const ed = E[+l.dataset.e]; pair(ed.s.id, ed.t.id); } else clear();
  });
  svg.addEventListener('wheel', e => {
    e.preventDefault(); const r = svg.getBoundingClientRect();
    const mx = (e.clientX - r.left) * W / r.width, my = (e.clientY - r.top) * H / r.height, f = Math.exp(-e.deltaY * .0015);
    view.x = mx - (mx - view.x) * f; view.y = my - (my - view.y) * f; view.k *= f; apply();
  }, {passive: false});
  const want = params.get('focus');
  if (want && byId[want]) focus(byId[want]);
};

function linkText(e) {
  const p = e.pics ? `${e.pics} ${e.pics === 1 ? 'picture' : 'pictures'} together` : '';
  const v = e.events ? `${e.events} ${e.events === 1 ? 'event' : 'events'}` : '';
  return [p, v].filter(Boolean).join(' · ');
}

/* ---------------- search / ask ---------------- */
function looksLikeQuestion(q) {
  return /\?$|^(when|who|what|where|why|how|did|do|was|were|is|are|tell|show me|מתי|מי|מה|איפה|למה|איך|ספר)\b/i.test(q.trim());
}
async function searchPage(_, params) {
  const q = params.get('q') || '';
  $('#q').value = q;
  const isQ = looksLikeQuestion(q);
  const r = await api(`/api/${isQ ? 'ask' : 'search'}?q=${enc(q)}`);
  const u = r.understood;
  const chips = [...u.people.map(x => `<span class="chip">${ic('people')}${esc(x)}</span>`),
    u.years[0] || u.years[1] ? `<span class="chip">${ic('calendar')}${u.years[0] || '…'}–${u.years[1] || '…'}</span>` : '',
    ...u.kinds.map(k => `<span class="chip">${esc(k)}s</span>`), ...u.words.slice(0, 6).map(w => `<span class="chip accent">${esc(w)}</span>`)].join('');
  const ans = isQ && r.answer ? `<div class="answer fade-in"><div class="eyebrow" style="color:var(--plum)">${ic('sparkle')} Muse answers from your pictures</div>
      <p dir="auto">${esc(r.answer).replace(/\[(\d+)\]/g, (m, n) => r.results[n - 1] ? `<sup><a href="#" data-cite="${esc(r.results[n - 1].id)}">${n}</a></sup>` : '')}</p>
      ${r.unsure ? '<div class="small muted" style="margin-top:8px">Your pictures don\'t fully answer this — here is what comes closest.</div>' : ''}</div>` : '';
  return `<div class="phead"><div><div class="eyebrow">${isQ ? 'Question' : 'Search'}</div><h1 dir="auto">${esc(q)}</h1></div></div>
    ${ans}
    <div class="understood">Muse understood: ${chips || '<span>everything</span>'} <span>· ${r.total} found</span></div>
    ${r.relaxed ? `<p class="small muted">No picture is linked to ${esc(u.people.join(' & '))} for this yet, so these are the closest matches without the name. <a href="#/faces">Naming faces</a> fixes that.</p>` : ''}
    ${r.results.length ? photosHtml(r.results, {why: true}) : `<div class="empty"><h2>Nothing found</h2><p>Try other words, a name, or a year.</p></div>`}`;
}
afterRender.search = () => {
  $$('[data-cite]').forEach(a => a.onclick = e => { e.preventDefault(); openViewer(a.dataset.cite); });
};

/* ---------------- who is this ---------------- */
let FACES = {faces: [], total: 0}, PEOPLE = [], GROUPS = null;
async function faces(_, params) {
  if (params.get('unclear')) return unclearFaces();
  GROUPS = await api('/api/face_groups');
  const g = GROUPS, named = g.open - g.no_fingerprint - g.waiting;
  return `<div class="phead"><div><div class="eyebrow">Who is this?</div><h1>Name a face once, name it everywhere</h1>
      <p>Faces that look like the same person are grouped, so one answer names all of them. Every card is a different person.
      A name is suggested only when the faces really match someone you already named.</p></div>
      <div style="min-width:240px"><div class="statline" style="margin:0"><div><b id="gleft">${g.total_groups}</b><span>people to name</span></div>
        <div><b>${named}</b><span>faces in them</span></div></div>
        ${g.waiting ? `<div class="small muted" style="margin-top:8px">Reading ${g.waiting} new faces…</div>` : ''}</div></div>
    <div id="grouplist" style="display:flex;flex-direction:column;gap:18px"></div>
    ${g.no_fingerprint ? `<div class="section card pad" style="display:flex;justify-content:space-between;align-items:center;gap:14px;flex-wrap:wrap">
      <div><h3>${g.no_fingerprint} faces were too unclear to group</h3><div class="small muted">Sunglasses, profiles, tiny or blurred faces. You can still name them one by one.</div></div>
      <a class="btn" href="#/faces?unclear=1">Name them one by one</a></div>` : ''}`;
}
function groupHtml(x) {
  const s = x.suggest, years = [...new Set(x.faces.map(f => f.date.slice(0, 4)).filter(Boolean))].sort();
  const span = years.length ? ` · ${years[0]}${years.length > 1 ? '–' + years.at(-1) : ''}` : '';
  const q = s ? (s.strong ? `Is this ${esc(s.name)}?` : `Could this be ${esc(s.name)}?`) : 'Who is this?';
  return `<article class="card group" data-g="${esc(x.id)}">
    <div class="gfaces">${x.faces.map(f => `<button class="gface" data-o="${esc(f.id)}" title="Tap to leave this face out">
      <img src="/api/crop/${enc(f.id)}" alt="face" loading="lazy"><span>${ic('close')}</span></button>`).join('')}
      ${x.size > x.faces.length ? `<div class="gmore">+${x.size - x.faces.length}</div>` : ''}</div>
    <div class="body">
      <div class="small faint">${x.size} ${x.size === 1 ? 'face' : 'faces'} · ${x.photos} ${x.photos === 1 ? 'picture' : 'pictures'}${span}</div>
      <div class="guess" dir="auto">${q}</div>
      ${x.size > 1 ? '<div class="small muted">Tap a face that is someone else to leave it out.</div>' : ''}
      <div class="acts">${s ? `<button class="btn primary" data-a="yes">${ic('check')}Yes, ${esc(s.name)}</button>` : ''}
        <button class="btn" data-a="skip">Skip</button><button class="btn ghost" data-a="not">Not a real person</button></div>
      <div class="peoplepick">${GROUPS.people.filter(p => !s || p.id !== s.id).map(p => `<button data-pid="${esc(p.id)}">${avatar(p)}${esc(p.name)}</button>`).join('')}</div>
      <form class="newname" style="display:flex;gap:8px"><input class="field" placeholder="Someone new — type their name" dir="auto" aria-label="New name">
        <button class="btn">Add</button></form></div></article>`;
}
function drawGroups() {
  const list = GROUPS.groups;
  $('#grouplist').innerHTML = list.length ? list.map(groupHtml).join('')
    : '<div class="empty card"><h2>Everyone is named</h2><p>Muse will ask again when new pictures arrive.</p></div>';
  if ($('#gleft')) $('#gleft').textContent = GROUPS.total_groups;
}
afterRender.faces = (_, params) => {
  if (params.get('unclear')) return afterUnclear();
  drawGroups();
  const send = async (card, body, label) => {
    const ids = $$('.gface:not(.off)', card).map(b => b.dataset.o);
    if (!ids.length) return toast('Every face is left out — nothing to save');
    card.style.opacity = .35;
    try {
      const r = await api('/api/answer_group', {obs_ids: ids, ...body});
      if (OV) OV.unknown_faces = Math.max(0, OV.unknown_faces - r.done.length);
      shell('faces');
      toast(`${label} · ${r.done.length} ${r.done.length === 1 ? 'face' : 'faces'}`, async () => {
        for (const id of r.done) await api('/api/undo', {obs_id: id});
        route();
      });
      card.remove();
      // names just given make the next suggestions better: regroup with them
      GROUPS = await api('/api/face_groups');
      drawGroups();
    } catch (e) { card.style.opacity = 1; toast(e.message); }
  };
  $('#grouplist').onclick = e => {
    const card = e.target.closest('[data-g]'); if (!card) return;
    const x = GROUPS.groups.find(g => g.id === card.dataset.g);
    const f = e.target.closest('.gface'); if (f) { f.classList.toggle('off'); return; }
    const b = e.target.closest('button'); if (!b || b.type === 'submit') return;
    if (b.dataset.pid) { const p = GROUPS.people.find(q => q.id === b.dataset.pid); return send(card, {action: 'confirm', person_id: p.id}, `Saved: ${p.name}`); }
    if (b.dataset.a === 'yes') return send(card, {action: 'confirm', person_id: x.suggest.id}, `Saved: ${x.suggest.name}`);
    if (b.dataset.a === 'skip') return send(card, {action: 'skip'}, 'Skipped');
    if (b.dataset.a === 'not') return send(card, {action: 'not_person'}, 'Not a person');
  };
  $('#grouplist').onsubmit = e => {
    e.preventDefault(); const name = $('input', e.target).value.trim();
    if (name) send(e.target.closest('[data-g]'), {action: 'confirm', new_name: name}, `Added ${name}`);
  };
};

async function unclearFaces() {
  [FACES, PEOPLE] = await Promise.all([api('/api/faces?limit=30&unclear=1'), api('/api/people')]);
  return `<a class="back" href="#/faces">${ic('back')}Groups</a>
    <div class="phead"><div><div class="eyebrow">Who is this?</div><h1>The unclear faces</h1>
      <p>Muse found a person here, but the face is turned away, covered or small, so it can't be grouped. Name the ones you recognise.</p></div>
      <div class="small muted" id="facecount">${FACES.total} faces to go</div></div>
    <div id="facelist" style="display:flex;flex-direction:column;gap:18px"></div>`;
}
function faceHtml(f) {
  const where = [when(f.date, null, true), f.album || f.event].filter(Boolean).join(' · ');
  return `<article class="card facecard" data-f="${esc(f.id)}">
    <div class="imgs"><img class="face" src="/api/crop/${enc(f.id)}" alt="face" loading="lazy">
      <img class="ctx" data-m="${esc(f.sha)}" src="${photo(f.sha)}" alt="whole picture" loading="lazy"></div>
    <div class="body"><div class="small faint" dir="auto">${esc(where)}</div>
      <div class="guess">Who is this?</div><div class="small muted" dir="auto">${esc(f.appearance || '')}</div>
      <div class="acts"><button class="btn" data-a="skip">Skip</button><button class="btn ghost" data-a="not">Not a person</button></div>
      <div class="peoplepick">${PEOPLE.map(p => `<button data-pid="${esc(p.id)}">${avatar(p)}${esc(p.name)}</button>`).join('')}</div>
      <form class="newname" style="display:flex;gap:8px"><input class="field" placeholder="Someone new — type their name" dir="auto" aria-label="New name">
        <button class="btn">Add</button></form></div></article>`;
}
function drawFaces() {
  $('#facelist').innerHTML = FACES.faces.length ? FACES.faces.map(faceHtml).join('') : '<div class="empty card"><h2>Nothing left here</h2></div>';
  $('#facecount').textContent = `${FACES.total} faces to go`;
}
function afterUnclear() {
  drawFaces();
  const answer = async (card, body, label) => {
    card.style.opacity = .35;
    try {
      await api('/api/answer', {obs_id: card.dataset.f, ...body});
      FACES.faces = FACES.faces.filter(f => f.id !== card.dataset.f); FACES.total--;
      if (OV) OV.unknown_faces = Math.max(0, OV.unknown_faces - 1);
      const id = card.dataset.f;
      toast(label, async () => { await api('/api/undo', {obs_id: id}); route(); });
      card.remove(); $('#facecount').textContent = `${FACES.total} faces to go`; shell('faces');
      if (body.new_name) PEOPLE = await api('/api/people');
      if (FACES.faces.length < 5 && FACES.total > FACES.faces.length) { FACES = await api('/api/faces?limit=30&unclear=1'); drawFaces(); }
    } catch (e) { card.style.opacity = 1; toast(e.message); }
  };
  $('#facelist').onclick = e => {
    const card = e.target.closest('[data-f]'); if (!card) return;
    const b = e.target.closest('button'); if (!b || b.type === 'submit') return;
    if (b.dataset.pid) { const p = PEOPLE.find(x => x.id === b.dataset.pid); return answer(card, {action: 'confirm', person_id: b.dataset.pid}, `Saved: ${p.name}`); }
    if (b.dataset.a === 'skip') return answer(card, {action: 'skip'}, 'Skipped');
    if (b.dataset.a === 'not') return answer(card, {action: 'not_person'}, 'Marked as not a person');
  };
  $('#facelist').onsubmit = e => {
    e.preventDefault(); const name = $('input', e.target).value.trim();
    if (name) answer(e.target.closest('[data-f]'), {action: 'confirm', new_name: name}, `Added ${name}`);
  };
}

/* ---------------- films ---------------- */
const CREW_COLORS = {Researcher: '#6d4c74', Producer: '#2f7d5b', Screenwriter: '#d9542a', Director: '#1e1916', 'Picture checker': '#b7791f',
  'Picture Checker': '#b7791f', Editor: '#3b5bdb', Narrator: '#0b7285', Composer: '#862e9c', Critic: '#c92a2a', 'Script check': '#5f564f'};
async function films(_, params) {
  const [list, ts, ps] = await Promise.all([api('/api/films'), api('/api/templates'), api('/api/persons')]);
  const idea = params.get('idea');
  const me = ps.find(p => p.owner), other = ps.find(p => !p.owner);
  const preset = params.get('req') || (idea === 'birthday' && other ? `A 60-second birthday film for ${other.name}, warm and a little funny, ending with everyone together.`
    : idea === 'together' && me && other ? `A one-minute film about ${me.name} and ${other.name} together, from the first picture to the last.`
    : idea === 'year' && OV?.years ? `A one-minute film of my year ${OV.years[1]}, in the order it happened.` : '');
  const quick = [
    ...ps.filter(p => !p.owner).slice(0, 3).map(p => [`Birthday: ${p.name}`, `A 60-second birthday film for ${p.name}, warm and a little funny, ending with everyone together.`]),
    me ? [`My story`, `A 90-second film of ${me.name}'s life so far, from childhood to today.`] : null,
  ].filter(Boolean);
  return `<div class="phead"><div><div class="eyebrow">Films</div><h1>Tell the crew what to make</h1>
      <p>A producer, a screenwriter, a picture checker, an editor, a narrator, a composer and a critic — all Muse — make a first cut,
      watch it, and re-cut it. They stop to ask you what only you know.</p></div></div>
    <div class="card composer"><textarea class="field" id="freq" dir="auto" placeholder="A 60-second film for grandma's 80th, warm and a little funny, ending with the grandchildren.">${esc(preset)}</textarea>
      <div class="quick">${quick.map(([l, r]) => `<button class="chip" data-req="${esc(r)}">${esc(l)}</button>`).join('')}</div>
      <div class="opts"><div class="chips"><select class="field" id="ftpl" style="width:auto;min-height:40px;padding:6px 36px 6px 14px"><option value="">Story shape: from the sentence</option>
        ${ts.map(t => `<option value="${esc(t.id)}">${esc(t.label)}</option>`).join('')}</select>
        <label class="toggle"><input type="checkbox" id="fask" checked>Ask me before cutting</label></div>
        <button class="btn primary lg" id="fmake">${ic('film')}Make the film</button></div></div>
    <div class="section"><div class="section-head"><h2>Your films</h2></div>
      ${list.length ? `<div class="fgrid">${list.map(filmCard).join('')}</div>` : '<div class="empty card">Your first film will appear here.</div>'}</div>
    <div class="section card pad"><div class="section-head" style="margin-bottom:8px"><div><h2>Blessings</h2>
      <p class="muted small">Send a link; family and friends record a few words from their phone. Muse picks the lines that belong in the film.</p></div></div>
      <div id="blist" class="small muted">…</div></div>`;
}
function filmCard(f) {
  const st = {running: '<span class="pill live">Making</span>', waiting: '<span class="pill wait">Waiting for you</span>',
              failed: '<span class="pill fail">Failed</span>', interrupted: '<span class="pill fail">Stopped</span>'}[f.status] || '';
  return `<a class="film" href="#/film/${enc(f.id)}" style="text-decoration:none"><div class="poster">
      ${f.cover ? `<img src="${photo(f.cover)}" alt="" loading="lazy">` : ''}<span class="state">${st}</span></div>
    <h3 dir="auto">${esc(f.title)}</h3><div class="small faint">${f.v2 != null ? `Critic ${f.v1}/10 → ${f.v2}/10` : esc(f.request.slice(0, 70))}</div></a>`;
}
afterRender.films = async () => {
  $$('[data-req]').forEach(b => b.onclick = () => { $('#freq').value = b.dataset.req; $('#freq').focus(); });
  $('#fmake').onclick = async () => {
    const request = $('#freq').value.trim(); if (!request) return $('#freq').focus();
    $('#fmake').disabled = true;
    try { const {id} = await api('/api/films', {request, template: $('#ftpl').value || null, ask: $('#fask').checked}); location.hash = `#/film/${id}`; }
    catch (e) { toast(e.message); $('#fmake').disabled = false; }
  };
  const reqs = await api('/api/blessing_requests');
  $('#blist').innerHTML = reqs.length ? reqs.map(r => {
    const url = `${location.origin}/bless/${r.token}`;
    return `<div style="padding:10px 0;border-top:1px solid var(--line)"><b style="color:var(--ink)">For ${esc(r.name)}</b>
      <button class="btn sm ghost" data-copy="${esc(url)}">${ic('link')}Copy link</button>
      ${r.items.map(it => `<div dir="auto">• ${esc(it.from_name)} — ${esc(it.status)}${it.result?.film_worthy?.[0] ? `: “${esc(it.result.film_worthy[0].text_en || it.result.film_worthy[0].text)}”` : ''}</div>`).join('') || '<div>No recordings yet.</div>'}</div>`;
  }).join('') : 'No blessing links yet — open a person and choose “Ask for blessings”.';
  $$('[data-copy]').forEach(b => b.onclick = () => { navigator.clipboard?.writeText(b.dataset.copy); toast('Link copied'); });
};

let filmTimer = null, filmPicked = {}, filmRendered = {};
async function filmPage(id) {
  filmPicked = {}; filmRendered = {};
  return `<a class="back" href="#/films">${ic('back')}Films</a><div id="filmbox"><div class="skeleton" style="height:200px"></div></div>`;
}
afterRender.film = id => pollFilm(id);
async function pollFilm(id) {
  clearTimeout(filmTimer);
  if (!location.hash.startsWith(`#/film/${id}`)) return;
  const st = await api(`/api/films/${enc(id)}`);
  renderFilm(st);
  if (['running', 'waiting'].includes(st.status)) filmTimer = setTimeout(() => pollFilm(id), 2000);
}
function crewHtml(st) {
  return `<div class="card pad"><h3 style="margin-bottom:10px">The crew at work</h3><div class="crew">${st.log.map(e => `<div class="e">
    <span class="t">${e.t.toFixed(0)}s</span><span class="who" style="background:${CREW_COLORS[e.who] || '#8f857c'}" title="${esc(e.who)}">${esc(e.who[0])}</span>
    <div><b>${esc(e.who)}</b> <span dir="auto">${esc(e.did)}</span>${e.why ? `<div class="why" dir="auto">${esc(e.why)}</div>` : ''}</div></div>`).join('')}</div></div>`;
}
function questionsHtml(st) {
  const qs = st.questions || []; if (!qs.length) return '';
  const waiting = st.status === 'waiting';
  const left = waiting && st.waiting_until ? Math.max(0, Math.round((st.waiting_until - Date.now() / 1000) / 60)) : 0;
  return `<div class="card pad ${waiting ? 'ask' : ''}"><div class="eyebrow">${waiting ? `The crew is waiting for you · ${left} min` : 'What the crew asked'}</div>
    <h2 style="margin:4px 0 6px">${waiting ? 'A few things only you know' : 'Your answers'}</h2>
    ${qs.map(q => `<div class="q"><h3 dir="auto">${esc(q.text)}</h3><div class="small muted" dir="auto">${esc(q.why)}</div>
      ${q.kind === 'identity' ? `<div class="pics"><img src="${esc(q.image)}" alt="face"><img src="${esc(q.context_image)}" alt="whole picture"></div>` : ''}
      <div class="opts" style="margin-top:10px">${q.options.map(o => {
        const sel = (filmPicked[q.id] ?? q.answer) === o.value, def = q.kind === 'pick' && o.value === q.default;
        return `<button class="opt ${sel ? 'sel' : ''} ${def ? 'def' : ''}" data-q="${esc(q.id)}" data-v="${esc(o.value)}" ${waiting ? '' : 'disabled'}>
          ${o.image ? `<img src="${esc(o.image)}" alt="">` : ''}<span dir="auto">${esc(o.label)}${def ? ' · crew\'s pick' : ''}</span></button>`; }).join('')}
        ${waiting ? `<button class="btn ghost" data-q="${esc(q.id)}" data-v="__crew__">Let the crew decide</button>` : ''}</div>
      ${q.outcome ? `<div class="done">${ic('check')} ${esc(q.outcome)}</div>` : ''}</div>`).join('')}</div>`;
}
function scenesHtml(st) {
  if (!st.scenes) return '';
  const pc = st.picture_check || {};
  return `<div class="card pad"><h3>Scenes</h3><div class="small muted" style="margin-bottom:12px">✕ = taken out by the picture checker (hover for why)</div><div class="scenes">${st.scenes.map(sc => {
    const chk = pc[String(sc.order)] || {verdicts: []}, v = Object.fromEntries(chk.verdicts.map(x => [x.moment_id, x]));
    return `<div class="scene"><div class="tiny faint">${sc.order}${sc.beat ? ` · ${esc(sc.beat.replace(/_/g, ' '))}` : ''} · ${esc(sc.emotion || '')}</div>
      <div class="thumbs">${sc.moments.map(m => `<div class="${v[m] && !v[m].keep ? 'out' : ''}" title="${esc(v[m]?.reason || '')}"><img src="${photo(m.split(':')[0])}" alt="" loading="lazy"></div>`).join('')}</div>
      <div class="small" dir="auto">${chk.narration_fix && sc.narration ? `<s class="faint">${esc(sc.narration)}</s><br>${esc(chk.narration_fix)}` : esc(sc.narration || '')}</div>
      <div class="tiny muted" dir="auto">${esc(chk.note || sc.intent)}</div></div>`; }).join('')}</div></div>`;
}
function versionHtml(st, v) {
  const x = (st.versions || {})[v];
  const label = v === 'v1' ? 'First cut' : 'After the critic';
  if (!x) return `<div class="card pad"><h3>${label}</h3><div class="empty" style="padding:40px 0">${st.status === 'running' ? 'Being made…' : '—'}</div></div>`;
  return `<div class="card pad"><div style="display:flex;justify-content:space-between;align-items:baseline"><h3>${label}</h3>
      ${x.score != null ? `<span class="score">${x.score}<span class="small faint">/10</span></span>` : ''}</div>
    <video id="vid_${v}" controls preload="metadata" playsinline src="/api/films/${enc(st.id)}/video/${v}?d=${x.duration}" style="margin-top:10px"></video>
    <div class="small muted" style="margin-top:8px">${x.duration ? x.duration.toFixed(0) + ' s · ' : ''}${esc(x.summary || '')}</div>
    ${v === 'v1' && x.notes ? x.notes.map(n => { const ap = (st.applied || []).some(a => a.includes(`shot ${n.shot}: ${n.op}`));
      return `<div class="note ${ap ? 'applied' : ''}"><button class="btn sm ghost" data-seek="${v}" data-t="${n.t}">${Math.floor(n.t / 60)}:${String(Math.floor(n.t % 60)).padStart(2, '0')}</button>
        <b>${esc(n.op)}</b>${ap ? ' · fixed in v2' : ''}<div>${esc(n.problem)}</div></div>`; }).join('') : ''}</div>`;
}
function renderFilm(st) {
  const box = $('#filmbox'); if (!box) return;
  const head = `<div class="phead" style="margin-bottom:18px"><div><div class="eyebrow">${{running: 'Being made', waiting: 'Waiting for you', done: 'Ready', failed: 'Failed', interrupted: 'Stopped'}[st.status] || esc(st.status)}</div>
    <h1 dir="auto">${esc(st.title || 'Planning…')}</h1><p dir="auto">“${esc(st.request)}”</p>${st.error ? `<p style="color:#c92a2a">${esc(st.error)}</p>` : ''}</div></div>`;
  const vkey = JSON.stringify(Object.entries(st.versions || {}).map(([k, v]) => [k, v.score ?? v.duration]));
  if (filmRendered.vkey !== vkey || !$('#fversions')) {
    box.innerHTML = `<div id="fhead">${head}</div><div id="fask"></div><div class="versions" id="fversions">${versionHtml(st, 'v1')}${versionHtml(st, 'v2')}</div>
      <div class="section" id="fscenes">${scenesHtml(st)}</div><div class="section" id="fcrew">${crewHtml(st)}</div>`;
    filmRendered.vkey = vkey; filmRendered.qkey = null;
  } else {
    $('#fhead').innerHTML = head; $('#fscenes').innerHTML = scenesHtml(st); $('#fcrew').innerHTML = crewHtml(st);
  }
  const qkey = JSON.stringify([st.status, (st.questions || []).map(q => [q.id, q.outcome]), filmPicked,
                               st.waiting_until ? Math.round((st.waiting_until - Date.now() / 1000) / 60) : 0]);
  if (filmRendered.qkey !== qkey) { $('#fask').innerHTML = questionsHtml(st) ? `<div style="margin-bottom:22px">${questionsHtml(st)}</div>` : ''; filmRendered.qkey = qkey; }
  if (st.status === 'waiting' && !filmRendered.askShown) { filmRendered.askShown = true; $('#fask').scrollIntoView({block: 'start', behavior: 'smooth'}); }
  const c = $('.crew'); if (c) c.scrollTop = c.scrollHeight;
  box.onclick = async e => {
    const qb = e.target.closest('button[data-q]');
    if (qb) {
      filmPicked[qb.dataset.q] = qb.dataset.v; filmRendered.qkey = null;
      try { await api(`/api/films/${enc(st.id)}/answers`, {answers: {[qb.dataset.q]: qb.dataset.v}}); } catch (err) { toast(err.message); }
      return pollFilm(st.id);
    }
    const sb = e.target.closest('[data-seek]');
    if (sb) { const v = $(`#vid_${sb.dataset.seek}`); v.currentTime = Math.max(0, +sb.dataset.t - .5); v.play(); v.scrollIntoView({block: 'center', behavior: 'smooth'}); }
  };
}

/* ---------------- viewer ---------------- */
let viewerIdx = -1;
async function openViewer(mid) {
  let i = LIST.indexOf(mid);
  if (i < 0) { LIST = [mid]; i = 0; }
  viewerIdx = i;
  const m = await api(`/api/moment/${enc(LIST[i])}`).catch(() => null);
  if (!m) return;
  let v = $('.viewer');
  if (!v) { v = document.createElement('div'); v.className = 'viewer'; $('#layer').append(v); document.body.style.overflow = 'hidden'; }
  const media = m.kind === 'video'
    ? `<video src="/api/media/${enc(m.sha)}" controls autoplay playsinline poster="${photo(m.sha)}"></video>`
    : m.kind === 'audio' ? `<audio src="/api/media/${enc(m.sha)}" controls autoplay></audio>`
    : `<img src="/api/media/${enc(m.sha)}" alt="${esc(m.summary || '')}">`;
  const boxes = m.kind === 'photo' ? [...m.faces.map(f => ({...f, known: true})), ...m.unknown_faces].map(f => {
    const [x1, y1, x2, y2] = f.bbox;
    return `<div class="box ${f.known ? '' : 'unknown'}" style="left:${x1 / 10}%;top:${y1 / 10}%;width:${(x2 - x1) / 10}%;height:${(y2 - y1) / 10}%"
      ${f.known ? `data-person="${esc(f.id)}"` : `data-face="${esc(f.obs)}"`}><span dir="auto">${f.known ? esc(f.name) : f.cand ? `${esc(f.cand)}?` : 'Who?'}</span></div>`; }).join('') : '';
  const said = m.said.length ? `<div><div class="label">Said</div>${m.said.map(u => `<p class="quote" dir="auto">“${esc(u.text)}”</p>${u.text_en && u.text_en !== u.text ? `<p class="small muted">${esc(u.text_en)}</p>` : ''}`).join('')}</div>` : '';
  v.innerHTML = `<div class="stage"><button class="iconbtn close" aria-label="Close">${ic('close')}</button>
      ${LIST.length > 1 ? `<button class="nav-btn prev" aria-label="Previous">${ic('left')}</button><button class="nav-btn next" aria-label="Next">${ic('right')}</button>` : ''}
      <div class="media">${media}${boxes}</div></div>
    <div class="info">
      <div><div class="label">${esc(when(m.date, m.date_source))}${m.place ? ' · ' + esc(m.place) : ''}</div><h3 dir="auto">${esc((m.event || 'A moment').replace(/^./, c => c.toUpperCase()))}</h3></div>
      ${m.people.length || m.unknown ? `<div><div class="label">Who</div><div class="chips">${m.people.map(p => `<a class="chip" href="#/person/${enc(p.id)}">${avatar(p)}${esc(p.name)}</a>`).join('')}
        ${m.unknown ? `<a class="chip accent" href="#/faces">${m.unknown} unnamed</a>` : ''}</div></div>` : ''}
      <div><div class="label">What Muse saw</div><p dir="auto">${esc(m.summary || '')}</p></div>
      ${said}
      ${m.mood.length ? `<div><div class="label">Feeling</div><div class="chips">${m.mood.map(x => `<span class="chip accent">${esc(x)}</span>`).join('')}</div></div>` : ''}
      ${m.objects.length ? `<div><div class="label">In the picture</div><div class="chips">${m.objects.map(x => `<span class="chip">${esc(x)}</span>`).join('')}</div></div>` : ''}
      ${m.date_why && !PRECISE.has(m.date_source) ? `<div><div class="label">How Muse dated it</div><p class="small muted" dir="auto">${esc(m.date_why)}</p></div>` : ''}
      ${m.questions.length ? `<div><div class="label">Muse is still wondering</div>${m.questions.map(q => `<p class="small muted" dir="auto">• ${esc(q)}</p>`).join('')}</div>` : ''}
      <div class="chips">${m.memory ? `<a class="btn sm" href="#/memory/${enc(m.memory)}">${ic('memories')}The whole memory</a>` : ''}
        ${m.kind === 'photo' && (m.faces.length || m.unknown_faces.length) ? `<button class="btn sm ghost" data-toggle>${ic('eye')}Faces</button>` : ''}</div>
    </div>`;
  v.onclick = async e => {
    if (e.target.closest('.close')) return closeViewer();
    if (e.target.closest('.prev')) return step(-1);
    if (e.target.closest('.next')) return step(1);
    if (e.target.closest('[data-toggle]')) return v.classList.toggle('hideboxes');
    const pb = e.target.closest('[data-person]'); if (pb) { location.hash = `#/person/${enc(pb.dataset.person)}`; return; }
    const fb = e.target.closest('[data-face]');
    if (fb) {
      const name = prompt('Who is this?');
      if (name && name.trim()) {
        const ppl = await api('/api/people');
        const hit = ppl.find(p => p.name.toLowerCase() === name.trim().toLowerCase());
        try {
          await api('/api/answer', hit ? {obs_id: fb.dataset.face, action: 'confirm', person_id: hit.id} : {obs_id: fb.dataset.face, action: 'confirm', new_name: name.trim()});
          toast(`Saved: ${name.trim()}`); openViewer(LIST[viewerIdx]);
        } catch (err) { toast(err.message); }
      }
    }
    if (e.target.closest('a')) closeViewer();
  };
}
function step(d) { if (LIST.length > 1) openViewer(LIST[(viewerIdx + d + LIST.length) % LIST.length]); }
function closeViewer() { const v = $('.viewer'); if (v) { v.remove(); document.body.style.overflow = ''; } }
addEventListener('keydown', e => {
  if (!$('.viewer')) return;
  if (e.key === 'Escape') closeViewer(); else if (e.key === 'ArrowRight') step(1); else if (e.key === 'ArrowLeft') step(-1);
});

route();
