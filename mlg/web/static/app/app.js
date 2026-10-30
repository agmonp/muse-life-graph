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
const en = p => (p && (p.name_en || p.name)) || '';   // film requests are written in English
const initials = n => (n || '?').split(/\s+/).map(w => w[0]).join('').slice(0, 2).toUpperCase();
function avatar(p, cls = '') {
  return `<img class="${cls}" src="${ref(p.id)}" alt="${esc(p.name)}" title="${esc(p.name)}" loading="lazy" data-name="${esc(p.name)}">`;
}
// a person without a reference picture gets their initials instead of a broken image
function initialsUrl(name) {
  const c = document.createElement('canvas'); c.width = c.height = 96;
  const g = c.getContext('2d'); g.fillStyle = '#e8d9cc'; g.fillRect(0, 0, 96, 96);
  g.fillStyle = '#8a5a3c'; g.font = '600 38px Inter, sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle';
  g.fillText(initials(name), 48, 50); return c.toDataURL();
}
document.addEventListener('error', e => {
  const img = e.target;
  if (!img.dataset || !img.dataset.name || img.dataset.failed) return;
  img.dataset.failed = 1;
  if (img.tagName === 'IMG') img.src = initialsUrl(img.dataset.name);
  else if (img.tagName === 'image') img.setAttribute('href', initialsUrl(img.dataset.name));   // SVG map nodes
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
// after a deploy the server's data can change shape: a page still running old code reloads itself
let lastVersionCheck = 0;
async function checkVersion() {
  if (Date.now() - lastVersionCheck < 30000) return;
  lastVersionCheck = Date.now();
  try {
    const v = await api('/api/version');
    if (window.BUILD && v.build !== window.BUILD) location.reload();
  } catch (e) { /* offline or restarting: try again on the next page */ }
}
document.addEventListener('visibilitychange', () => { if (!document.hidden) checkVersion(); });

async function route() {
  checkVersion();
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
  demoBanner();
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

/* ---------------- the hosted demo ---------------- */
function demoBanner() {
  if (!OV || !OV.site || $('#demo-banner')) return;
  let closed = false;
  try { closed = sessionStorage.getItem('demo-banner') === 'closed'; } catch (e) { /* private mode */ }
  if (closed) return;
  $('#page').insertAdjacentHTML('beforebegin', `<div id="demo-banner" class="demo-banner">
    <span><b>A live demo.</b> This is one family's real life graph, shared with their consent: ${OV.photos.toLocaleString()} photos and
    ${OV.videos} videos, read by Muse. The product itself runs on <b>your own computer, on your own photos</b> — nothing leaves it
    except the calls to Meta's models. Here you can browse, search, ask and make films; names can't be changed.</span>
    <span class="chips"><a class="btn sm primary" href="${esc(OV.repo)}#run-it-on-your-own-photos" target="_blank" rel="noopener">Run it on your photos</a>
    <button class="btn sm ghost" data-close aria-label="Close">${ic('close')}</button></span></div>`);
  $('#demo-banner [data-close]').onclick = () => {
    $('#demo-banner').remove();
    try { sessionStorage.setItem('demo-banner', 'closed'); } catch (e) { /* private mode */ }
  };
}

function siteAddPage() {
  return `<div class="phead"><div><div class="eyebrow">Add photos</div><h1>On your own computer</h1>
      <p>This demo shows one family's library. Muse Life Graph is made to run where your photos are: on your computer,
      reading a folder or your Facebook / Instagram download in place. Your files never leave it.</p></div></div>
    <div class="card pad steps">
      <div class="step"><span class="dot">1</span><div><b>Install</b><div class="small muted">Python 3.12+, then the project from GitHub (one command in the README).</div></div></div>
      <div class="step"><span class="dot">2</span><div><b>Your Meta Model API key</b><div class="small muted">Muse Spark, Wonder, Voice Transcribe and Muse Image do the understanding.</div></div></div>
      <div class="step"><span class="dot">3</span><div><b>Choose a folder or your Meta download</b><div class="small muted">Copies are found and set aside, the cost is shown before Muse looks.</div></div></div>
      <div class="step"><span class="dot">4</span><div><b>Your life graph</b><div class="small muted">Memories, people, circles, search and films, all on your machine.</div></div></div>
      <a class="btn primary" style="align-self:flex-start;margin-top:8px" href="${esc(OV.repo)}#run-it-on-your-own-photos" target="_blank" rel="noopener">Instructions on GitHub</a></div>`;
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
  if (OV && OV.site) return siteAddPage();
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
  if (OV && OV.site) return;
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
  const [feat, fg] = await Promise.all([api('/api/featured').catch(() => ({film: null})),
                                        api('/api/face_groups?limit=5&per=1').catch(() => ({groups: [], open: 0}))]);
  const f = feat.film;
  const mm = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
  const crewLine = f ? f.crew.filter(w => w !== 'Director').map(w => `<span class="crewchip" style="--c:${CREW_COLORS[w] || '#8f857c'}">${esc(w)}</span>`)
    .join(`<span class="arrow">${ic('arrow')}</span>`) : '';
  const v1 = f?.versions.v1 || {}, v2 = f?.versions.v2 || {};
  const screening = f ? `<section class="screening fade-in">
      <div class="screen">
        <video id="fv" controls playsinline preload="metadata" poster="${f.cover ? photo(f.cover) : ''}" src="/api/films/${enc(f.id)}/video/v2"></video>
        <div class="vtabs" role="tablist">
          <button class="on" data-v="v2" role="tab">After the critic${v2.score != null ? ` · ${v2.score}/10` : ''}</button>
          <button data-v="v1" role="tab">First cut${v1.score != null ? ` · ${v1.score}/10` : ''}</button></div>
      </div>
      <div class="story">
        <div class="eyebrow">Made by Muse from one sentence</div>
        <h1 dir="auto">${esc(f.title || 'A film')}</h1>
        <blockquote dir="auto">“${esc(f.request)}”</blockquote>
        <div class="crewline">${crewLine}</div>
        <div class="filmstats">
          <div><b>${f.scenes}</b><span>scenes</span></div>
          <div><b>${f.made_in ? Math.round(f.made_in / 60) : '–'}</b><span>minutes</span></div>
          <div><b>${f.asked}</b><span>asked you</span></div>
          <div><b>${(v1.notes || []).length}</b><span>critic notes</span></div></div>
        <p class="small">The crew read ${o.photos.toLocaleString()} photos and ${o.videos} videos, wrote the story, checked every picture,
          cut a first version, then <b>watched it</b> — and re-cut it from the critic's notes. It stopped to ask about faces only you know.</p>
        <div class="chips"><a class="btn primary" href="#/films">${ic('film')}Make your own film</a>
          <a class="btn ghost" href="#/film/${enc(f.id)}">See how it was made</a></div>
      </div>
        <div class="critic" id="fcritic">
          <div class="eyebrow">What the critic saw in the first cut</div>
          <div class="hint">Muse Wonder watched the draft and wrote these notes; the editor applied them. Tap one to see that moment.</div>
          <div class="strip">${(v1.notes || []).map((n, i) => `<button class="mark" style="left:${Math.min(98, 100 * n.t / (v1.duration || 60)).toFixed(1)}%" data-t="${n.t}" title="${esc(n.problem)}">${i + 1}</button>`).join('')}</div>
          <div class="notelist">${(v1.notes || []).slice(0, 4).map((n, i) => `<button class="noterow" data-t="${n.t}"><b>${i + 1}</b><span><span class="tiny faint">${mm(n.t)} · ${esc(n.op)}</span><br>${esc(n.problem)}</span></button>`).join('')}</div>
        </div>
      </section>` : '';
  const hello = `<div class="${f ? 'hello2' : 'hello'}">
      <div class="intro">
        <div class="eyebrow">${greeting()}${o.owner ? `, ${esc(o.owner)}` : ''}</div>
        ${f ? '<h2>Tell the crew what to make</h2>' : '<h1>Here is your life,<br>as Muse sees it.</h1>'}
        <div class="stats"><span><b>${o.photos.toLocaleString()}</b> photos</span><span><b>${o.videos}</b> videos</span><span><b>${o.people}</b> people</span>
          <span><b>${o.memories}</b> memories</span>${o.years ? `<span><b>${o.years[0]}–${o.years[1]}</b></span>` : ''}</div>
        <form class="askbox" id="makeform"><input id="makeq" dir="auto" placeholder="A one-minute film for grandma's 80th, warm and a little funny" aria-label="Describe a film">
          <button class="btn primary">${ic('film')}Make it</button></form>
        <div class="suggest">
          <button class="chip" data-film="birthday">${ic('cake')}A birthday film</button>
          <button class="chip" data-film="together">${ic('together')}The two of us</button>
          <button class="chip" data-film="year">${ic('calendar')}A year in a minute</button></div>
      </div></div>`;
  const faces = fg.open ? `<div class="card needs">
      <div class="facestack">${fg.groups.slice(0, 5).map(g => `<img src="/api/crop/${enc(g.faces[0].id)}" alt="" loading="lazy">`).join('')}</div>
      <div><h3>${fg.open.toLocaleString()} faces Muse couldn't name yet</h3><div class="small muted">Faces that look alike are grouped, so one answer names many${OV.site ? ' (on this demo, answers are kept for your visit only)' : ''}.</div></div>
      <a class="btn" href="#/faces">Who is this? ${ic('arrow')}</a></div>` : '';
  const circles = `<a class="card circlescard" href="#/connections">
      <div><div class="eyebrow">The circles of your life</div><h3>${o.people} people in their circles, from ${o.years ? o.years[0] : ''} to today</h3>
      <div class="small muted">Watch the circles form, grow and fade — year by year. Who bridges them, who is new, who you haven't seen in years.</div></div>
      <span class="btn primary">${ic('play')}Watch them grow</span></a>`;
  const asks = [`When was I happiest?`, `Photos of me as a child`, `Who do I spend the most time with?`];
  return `${screening}${hello}
    <div class="section duo">${circles}${faces}</div>
    <div class="section"><div class="section-head"><div><h2>${o.on_this_day.length ? 'On this day' : 'Recent memories'}</h2><p class="muted small">Moments that belong together, titled by Muse</p></div>
      <a class="btn ghost sm" href="#/memories">All memories ${ic('arrow')}</a></div>
      <div class="row-scroll">${(o.on_this_day.length ? o.on_this_day : o.recent).map(memCard).join('')}</div></div>
    <div class="section"><div class="section-head"><div><h2>Or ask your life</h2><p class="muted small">Answers come with the pictures they are based on.</p></div></div>
      <div class="suggest">${asks.map(a => `<button class="chip" data-ask="${esc(a)}">${esc(a)}</button>`).join('')}</div></div>`;
}
afterRender[''] = () => {
  $$('[data-ask]').forEach(b => b.onclick = () => { location.hash = `#/search?q=${enc(b.dataset.ask)}`; });
  $$('[data-film]').forEach(b => b.onclick = () => { location.hash = `#/films?idea=${b.dataset.film}`; });
  $('#makeform').onsubmit = async e => {
    e.preventDefault();
    const request = $('#makeq').value.trim();
    if (!request) return $('#makeq').focus();
    try { const {id} = await api('/api/films', {request, ask: true}); location.hash = `#/film/${id}`; }
    catch (err) { toast(err.message); }
  };
  const v = $('#fv');
  if (!v) return;
  const id = v.src.split('/video/')[0];
  $$('.vtabs button').forEach(b => b.onclick = () => {
    $$('.vtabs button').forEach(x => x.classList.toggle('on', x === b));
    v.src = `${id}/video/${b.dataset.v}`; v.play().catch(() => {});
  });
  $('#fcritic').onclick = e => {
    const m = e.target.closest('[data-t]'); if (!m) return;
    if (!v.src.endsWith('/v1')) { $$('.vtabs button')[1].click(); }
    const go = () => { v.currentTime = Math.max(0, +m.dataset.t - .5); v.play().catch(() => {}); };
    v.readyState >= 1 ? go() : v.addEventListener('loadedmetadata', go, {once: true});
  };
};

/* ---------------- memories ---------------- */
async function memories(_, params) {
  const all = await api('/api/memories');
  const years = [...new Set(all.map(x => x.date.slice(0, 4)))].sort().reverse();
  const y = params.get('year');
  const shown = y ? all.filter(x => x.date.startsWith(y)) : all;
  return `<div class="phead"><div><div class="eyebrow">Memories</div><h1>Moments that belong together</h1>
      <p>Muse groups the pictures of one day, one trip or one old album page, and names each memory from what it sees.</p></div></div>
    <div class="chips yearchips" style="margin-bottom:24px"><a class="chip ${y ? '' : 'on'}" href="#/memories">All</a>
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
          <a class="btn primary sm" href="#/films?req=${enc(`A 60-second birthday film for ${en(p)}, warm and a little funny.`)}">${ic('cake')}Birthday film</a>
          <a class="btn sm" href="#/search?q=${enc(`Tell me about ${en(p)}`)}">${ic('sparkle')}Ask about ${esc(p.name.split(' ')[0])}</a>
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
const CIRCLE_COLORS = ['#d9542a', '#6d4c74', '#2f7d5b', '#3b5bdb', '#b7791f', '#c2255c', '#0b7285', '#5c940d', '#862e9c', '#e8590c', '#1864ab', '#5f3dc4'];
async function connections() {
  return `<div class="phead"><div><div class="eyebrow">Connections</div><h1>The circles of your life</h1>
      <p>Each island is a circle — your own groups from the Life Graph, or one Muse found and named. People who are photographed
      together are close; the lines are the ties that stand out. Click anyone to see who they are with.</p></div></div>
    <div class="netwrap"><div class="graphwrap" id="gw"><svg id="gsvg" aria-label="Map of the people in your life"></svg>
      <div class="gtools"><button class="iconbtn" data-z="in" aria-label="Zoom in">${ic('plus')}</button>
        <button class="iconbtn" data-z="out" aria-label="Zoom out"><svg class="icon"><path d="M5 12h14"/></svg></button>
        <button class="iconbtn" data-z="fit" aria-label="Fit">${ic('graph')}</button>
        <label class="toggle small"><input type="checkbox" id="gme">My ties</label></div>
      <div class="glegend" id="glegend"></div>
      <div class="timebar" id="timebar" hidden>
        <button class="iconbtn" id="tplay" aria-label="Play the years">${ic('play')}</button>
        <div class="tslide"><svg class="thist" id="thist" preserveAspectRatio="none"></svg>
          <input type="range" id="tyear" min="0" max="1" value="1" aria-label="Year"></div>
        <div class="tyear"><b id="tylabel">All years</b><span id="tycap" class="tiny faint"></span></div>
        <button class="btn sm ghost" id="tall">All years</button></div></div>
      <aside class="card netside" id="netside"><div class="skeleton" style="height:240px"></div></aside></div>`;
}
function linkText(t) {
  const p = t.pics ? `${t.pics} ${t.pics === 1 ? 'picture' : 'pictures'}` : '';
  const v = t.events ? `${t.events} ${t.events === 1 ? 'event' : 'events'}` : '';
  return [p, v].filter(Boolean).join(' · ');
}
const yrs = t => t.from ? (t.from === t.to ? t.from : `${t.from}–${t.to}`) : '';
afterRender.connections = async (_, params) => {
  const [g, ins] = await Promise.all([api('/api/graph'), api('/api/insights')]);
  const svg = $('#gsvg'), wrap = $('#gw'), side = $('#netside');
  if (!g.nodes.length) { wrap.innerHTML = '<div class="empty"><h2>No people yet</h2><p><a href="#/faces">Name a few faces</a> and the map appears.</p></div>'; return; }
  const color = {}; g.circles.slice().sort((a, b) => b.size - a.size).forEach((c, i) => { color[c.name] = CIRCLE_COLORS[i % CIRCLE_COLORS.length]; });
  const byId = Object.fromEntries(g.nodes.map(n => [n.id, n]));
  const ex = [...g.nodes.map(n => [n.x - n.r, n.y - n.r, n.x + n.r, n.y + n.r + 18]), ...g.circles.map(c => [c.x - c.r, c.y - c.r - 30, c.x + c.r, c.y + c.r])];
  const X0 = Math.min(...ex.map(e => e[0])) - 30, Y0 = Math.min(...ex.map(e => e[1])) - 30;
  const X1 = Math.max(...ex.map(e => e[2])) + 30, Y1 = Math.max(...ex.map(e => e[3])) + 30;
  if (innerWidth < 980) {   // narrow screens: the box takes the map's own proportions, no empty bands
    wrap.style.height = `${Math.round(Math.max(320, Math.min(innerHeight * .7, wrap.clientWidth * (Y1 - Y0) / (X1 - X0) + 200)))}px`;   // + the zoom tools and the year bar
    wrap.style.minHeight = '0';
  }
  const W = wrap.clientWidth, H = wrap.clientHeight;
  let view;
  const TOP = 58, BOTTOM = 120;   // screen pixels kept free for the zoom tools and the year bar
  const fit = () => { const k = Math.min(W / (X1 - X0), (H - TOP - BOTTOM) / (Y1 - Y0)); view = {k, x: W / 2 - k * (X0 + X1) / 2, y: TOP + (H - TOP - BOTTOM) / 2 - k * (Y0 + Y1) / 2}; };
  fit();
  const maxW = Math.max(...g.edges.filter(e => !e.owner).map(e => e.w), 0.01);
  const edge = (e, cls) => { const a = byId[e.a], b = byId[e.b]; if (!a || !b) return '';
    const inside = e.inside && !e.owner;
    return `<line class="gedge ${cls}" data-a="${esc(e.a)}" data-b="${esc(e.b)}" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}"
      stroke="${inside ? color[a.circle] : 'var(--ink-3)'}" stroke-width="${(1 + 6 * e.w / maxW).toFixed(1)}"
      ${inside ? '' : 'stroke-dasharray="3 6"'}><title>${esc(a.name)} & ${esc(b.name)}: ${linkText(e)}</title></line>`; };
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.innerHTML = `<defs>${g.nodes.map((n, i) => `<clipPath id="c${i}"><circle r="${n.r}"/></clipPath>`).join('')}</defs><g id="gv">
    <g class="islands">${g.circles.map(c => `<g class="island" data-circle="${esc(c.name)}">
      <circle cx="${c.x}" cy="${c.y}" r="${c.r}" fill="${color[c.name]}" fill-opacity=".07" stroke="${color[c.name]}" stroke-opacity=".25" stroke-width="2"/>
      <text x="${c.x}" y="${c.y - c.r - 10}" text-anchor="middle" fill="${color[c.name]}" style="font-size:${Math.max(15, c.r / 7).toFixed(0)}px">${esc(c.name)} · ${c.size}</text></g>`).join('')}</g>
    <g class="edges">${g.edges.filter(e => !e.owner).map(e => edge(e, '')).join('')}</g>
    <g class="edges owner-edges" style="display:none">${g.edges.filter(e => e.owner).map(e => edge(e, 'own')).join('')}</g>
    <g class="egos"></g>
    <g class="nodes">${g.nodes.map((n, i) => `<g class="gnode ${n.owner ? 'owner' : ''} ${n.bridge >= 0.04 ? 'bridge' : ''} ${n.r >= 24 || n.owner ? 'big' : ''}"
        data-id="${esc(n.id)}" transform="translate(${n.x},${n.y})">
      <circle r="${n.r + 3}" fill="${n.owner ? 'var(--accent)' : color[n.circle] || 'var(--ink-3)'}"/>
      <circle r="${n.r}" fill="var(--bg-2)"/><image href="${ref(n.id)}" data-name="${esc(n.name)}" x="${-n.r}" y="${-n.r}" width="${2 * n.r}" height="${2 * n.r}" clip-path="url(#c${i})" preserveAspectRatio="xMidYMid slice"/>
      ${n.bridge >= 0.04 ? `<circle class="bridge-ring" r="${n.r + 8}"/>` : ''}
      <text y="${n.r + 16}" text-anchor="middle" dir="auto">${esc(n.name.length > 18 ? n.name.slice(0, 17) + '…' : n.name)}</text></g>`).join('')}</g></g>`;
  const gv = $('#gv');
  const apply = () => { gv.setAttribute('transform', `translate(${view.x},${view.y}) scale(${view.k})`); svg.classList.toggle('zoomed', view.k > 1.15 * Math.min(W / (X1 - X0), H / (Y1 - Y0))); };
  apply();
  $('#glegend').innerHTML = `<span>${g.stats.people} people · ${g.stats.backbone} strong ties of ${g.stats.ties} · ${g.stats.circles} circles</span>
    <span title="Ties are normalised for how often each person appears; the disparity filter (Serrano et al. 2009) keeps the significant ones; circles by your Life Graph groups and Louvain communities (modularity ${g.stats.modularity}); dashed rings mark bridges (betweenness).">ⓘ how</span>`;
  $('#gme').onchange = e => { $('.owner-edges', svg).style.display = e.target.checked ? '' : 'none'; };

  // ---- side panel: the overview, or one person ----
  const tieRow = (t, me) => `<a href="#" class="tie" data-pair="${esc(me)}|${esc(t.id)}">${avatar(t)}<span><b dir="auto">${esc(t.name)}</b>
      <span class="tiny faint">${linkText(t)}${yrs(t) ? ' · ' + yrs(t) : ''}</span></span>
      <i class="bar" style="--w:${Math.min(100, Math.round(100 * t.strength / Math.max(.01, (window._maxS || 1))))}%"></i></a>`;
  const overview = () => {
    clear();
    side.innerHTML = `<div class="eyebrow">Your circles</div>
      <div class="chips" style="margin:10px 0 18px">${g.circles.slice().sort((a, b) => b.size - a.size).map(c =>
        `<button class="chip" data-goto="${esc(c.name)}"><i class="dot" style="background:${color[c.name]}"></i>${esc(c.name)} · ${c.size}</button>`).join('')}</div>
      ${ins.closest?.length ? `<div class="label tiny faint">Closest to you</div><div class="withlist">${ins.closest.map(t => person(t, `${t.pics} pictures together · ${yrs(t)}`)).join('')}</div>` : ''}
      ${ins.bridges?.length ? `<div class="label tiny faint" style="margin-top:16px">Bridges between circles</div><div class="withlist">${ins.bridges.slice(0, 4).map(b =>
        person(b, b.joins.length ? `connects ${b.joins.map(esc).join(', ')}` : 'between circles')).join('')}</div>` : ''}
      ${ins.fading?.length ? `<div class="label tiny faint" style="margin-top:16px">Not seen together lately</div><div class="withlist">${ins.fading.slice(0, 4).map(t =>
        person(t, `last together ${t.to} · ${t.pics + t.events} times before`)).join('')}</div>` : ''}
      ${ins.rising?.length ? `<div class="label tiny faint" style="margin-top:16px">New in your life</div><div class="withlist">${ins.rising.slice(0, 4).map(t =>
        person(t, `since ${t.from} · ${linkText(t)}`)).join('')}</div>` : ''}`;
  };
  const person = (p, sub) => `<a href="#" data-focus="${esc(p.id)}">${avatar(p)}<span><b dir="auto">${esc(p.name)}</b><br><span class="tiny faint">${sub}</span></span></a>`;
  const clear = () => { $$('.dim', svg).forEach(el => el.classList.remove('dim')); $$('.on', svg).forEach(el => el.classList.remove('on')); $('.egos', svg).innerHTML = ''; };
  const focus = async id => {
    const n = byId[id]; if (!n) return;
    const t = await api(`/api/ties/${enc(id)}`);
    window._maxS = Math.max(.01, ...t.ties.map(x => x.strength));
    const near = new Set([id, ...t.ties.map(x => x.id)]);
    $$('.gnode', svg).forEach(el => el.classList.toggle('dim', !near.has(el.dataset.id)));
    $$('.gedge', svg).forEach(el => el.classList.add('dim'));
    $$('.island', svg).forEach(el => el.classList.toggle('dim', !t.ties.some(x => byId[x.id]?.circle === el.dataset.circle) && n.circle !== el.dataset.circle));
    $('.egos', svg).innerHTML = t.ties.filter(x => byId[x.id]).map(x => { const o = byId[x.id];
      return `<line class="ego" x1="${n.x}" y1="${n.y}" x2="${o.x}" y2="${o.y}" stroke="${n.owner ? 'var(--accent)' : color[n.circle]}"
        stroke-width="${(1 + 7 * x.strength / window._maxS).toFixed(1)}" stroke-opacity="${(.25 + .6 * x.strength / window._maxS).toFixed(2)}"/>`; }).join('');
    $$('.gnode', svg).forEach(el => el.classList.toggle('on', el.dataset.id === id));
    side.innerHTML = `<div style="display:flex;gap:14px;align-items:center">${avatar(n, 'portrait" style="width:72px;height:72px;border-width:3px')}
      <div><h3 dir="auto">${esc(n.name)}</h3><div class="small muted">${n.count} pictures${n.relation ? ' · ' + esc(n.relation) : ''}</div>
      <div class="chips" style="margin-top:6px"><span class="chip"><i class="dot" style="background:${n.owner ? 'var(--accent)' : color[n.circle]}"></i>${esc(n.owner ? 'You' : n.circle)}</span></div></div></div>
      ${n.bridge >= 0.04 ? `<p class="small muted" style="margin:12px 0 0">A bridge: their ties link circles that are otherwise apart.</p>` : ''}
      <div class="label tiny faint" style="margin:16px 0 6px">With whom, by pictures together</div>
      <div class="withlist ties">${t.ties.slice(0, 30).map(x => tieRow(x, id)).join('') || '<span class="small muted">Not in a picture with anyone named yet.</span>'}</div>
      <div class="chips" style="margin-top:14px"><a class="btn sm primary" href="#/person/${enc(id)}">Open page</a><button class="btn sm ghost" data-back>All circles</button></div>`;
    if (innerWidth < 760) side.scrollIntoView({behavior: 'smooth', block: 'start'});
  };
  const pair = async (a, b) => {
    const ms = await api(`/api/shared?a=${enc(a)}&b=${enc(b)}`);
    const na = byId[a] || {name: ''}, nb = byId[b] || {name: ''};
    side.innerHTML = `<button class="btn sm ghost" data-focus="${esc(a)}">${ic('back')}${esc(na.name)}</button>
      <h3 style="margin:10px 0 4px" dir="auto">${esc(na.name)} & ${esc(nb.name)}</h3><div class="small muted" style="margin-bottom:10px">${ms.length} pictures</div>
      ${photosHtml(ms.slice(0, 16)).replace('class="photos"', 'class="photos" style="columns:2 120px"')}
      <a class="btn sm primary" style="margin-top:10px" href="#/films?req=${enc(`A one-minute film about ${en(na)} and ${en(nb)} together, from the first picture to the last.`)}">${ic('film')}Film of the two</a>`;
  };
  side.onclick = e => {
    const f = e.target.closest('[data-focus]'); if (f) { e.preventDefault(); return focus(f.dataset.focus); }
    const p = e.target.closest('[data-pair]'); if (p) { e.preventDefault(); const [a, b] = p.dataset.pair.split('|'); return pair(a, b); }
    const c = e.target.closest('[data-goto]'); if (c) { const ci = g.circles.find(x => x.name === c.dataset.goto); zoomTo(ci.x, ci.y, ci.r); return; }
    if (e.target.closest('[data-back]')) { overview(); }
  };
  const zoomTo = (x, y, r) => { const k = Math.min(3, Math.min(W, H) / (2.4 * r)); view = {k, x: W / 2 - k * x, y: H / 2 - k * y}; gv.style.transition = 'transform .4s'; apply(); setTimeout(() => gv.style.transition = '', 450); };
  overview();

  // ---- pan, zoom, pinch, click ----
  const pts = new Map(); let drag = null, moved = false, pinch = null;
  const toWorld = (cx, cy) => { const r = svg.getBoundingClientRect(); return [(cx - r.left) * W / r.width, (cy - r.top) * H / r.height]; };
  const zoomAt = (mx, my, f) => { view.x = mx - (mx - view.x) * f; view.y = my - (my - view.y) * f; view.k *= f; apply(); };
  svg.addEventListener('pointerdown', e => { pts.set(e.pointerId, [e.clientX, e.clientY]); svg.setPointerCapture(e.pointerId);
    if (pts.size === 1) { drag = {x: e.clientX, y: e.clientY, vx: view.x, vy: view.y}; moved = false; }
    if (pts.size === 2) { const [p1, p2] = [...pts.values()]; pinch = {d: Math.hypot(p1[0] - p2[0], p1[1] - p2[1]), k: view.k}; } });
  svg.addEventListener('pointermove', e => {
    if (!pts.has(e.pointerId)) return; pts.set(e.pointerId, [e.clientX, e.clientY]);
    if (pts.size === 2 && pinch) { const [p1, p2] = [...pts.values()]; const d = Math.hypot(p1[0] - p2[0], p1[1] - p2[1]);
      const [mx, my] = toWorld((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2); zoomAt(mx, my, (pinch.k * d / pinch.d) / view.k); moved = true; return; }
    if (!drag) return; const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (Math.abs(dx) + Math.abs(dy) > 4) moved = true;
    const r = svg.getBoundingClientRect(); view.x = drag.vx + dx * W / r.width; view.y = drag.vy + dy * H / r.height; apply(); });
  const up = e => { pts.delete(e.pointerId); if (pts.size < 2) pinch = null; if (pts.size) return; drag = null; if (moved) return;
    const hit = document.elementFromPoint(e.clientX, e.clientY) || e.target;
    const n = hit.closest('.gnode'), l = hit.closest('.gedge');
    if (n) focus(n.dataset.id); else if (l) pair(l.dataset.a, l.dataset.b); else overview(); };
  svg.addEventListener('pointerup', up); svg.addEventListener('pointercancel', e => { pts.delete(e.pointerId); drag = null; pinch = null; });
  svg.addEventListener('wheel', e => { e.preventDefault(); const [mx, my] = toWorld(e.clientX, e.clientY); zoomAt(mx, my, Math.exp(-e.deltaY * .0015)); }, {passive: false});
  $$('.gtools [data-z]').forEach(b => b.onclick = () => { if (b.dataset.z === 'fit') { fit(); apply(); } else zoomAt(W / 2, H / 2, b.dataset.z === 'in' ? 1.3 : 1 / 1.3); });
  const want = params.get('focus');
  if (want && byId[want]) { focus(want); zoomTo(byId[want].x, byId[want].y, 260); }
  timeline(svg, g, byId);
};

// the circles through time: everyone stays where they are; each year lights up who was there and with whom
async function timeline(svg, g, byId) {
  const t = await api('/api/graph/years').catch(() => null);
  if (!t || t.years.length < 2) return;
  const bar = $('#timebar'), slider = $('#tyear');
  bar.hidden = false;
  slider.max = t.years.length;   // the last stop is "all years"
  slider.value = t.years.length;
  const maxP = Math.max(...t.photos);
  $('#thist').setAttribute('viewBox', `0 0 ${t.years.length} 10`);
  $('#thist').innerHTML = t.photos.map((n, i) => `<rect x="${i + .12}" width=".76" y="${10 - 10 * Math.sqrt(n / maxP)}" height="${10 * Math.sqrt(n / maxP)}"/>`).join('');
  const first = {};
  for (const [pid, ys] of Object.entries(t.people)) first[pid] = Object.keys(ys).sort()[0];
  const tieYears = Object.fromEntries(t.ties.map(x => [[x.a, x.b].sort().join('|'), x.years]));
  const nodes = $$('.gnode', svg), edges = $$('.gedge', svg), islands = $$('.island', svg);
  const show = i => {
    const y = t.years[i];
    if (!y) {   // all years
      nodes.forEach(n => { n.classList.remove('ghost', 'lit', 'fresh'); n.setAttribute('transform', `translate(${byId[n.dataset.id].x},${byId[n.dataset.id].y})`); });
      edges.forEach(e => e.classList.remove('ghost', 'lit'));
      islands.forEach(c => c.classList.remove('ghost'));
      $('#tylabel').textContent = 'All years'; $('#tycap').textContent = `${g.stats.people} people`;
      $('#thist').querySelectorAll('rect').forEach(r => r.classList.remove('on'));
      return;
    }
    const counts = Object.fromEntries(Object.entries(t.people).map(([p, ys]) => [p, ys[y] || 0]));
    const maxC = Math.max(1, ...Object.values(counts));
    const lit = new Set(), circlesLit = new Set();
    nodes.forEach(n => {
      const id = n.dataset.id, c = counts[id] || 0, nd = byId[id];
      const on = c > 0 || nd.owner;
      n.classList.toggle('ghost', !on); n.classList.toggle('lit', on); n.classList.toggle('fresh', first[id] === y);
      const k = on ? .75 + .55 * Math.sqrt(c / maxC) : .6;
      n.setAttribute('transform', `translate(${nd.x},${nd.y}) scale(${k.toFixed(2)})`);
      if (on) { lit.add(id); circlesLit.add(nd.circle); }
    });
    edges.forEach(e => { const n = (tieYears[[e.dataset.a, e.dataset.b].sort().join('|')] || {})[y] || 0;
      e.classList.toggle('lit', n > 0); e.classList.toggle('ghost', !n); });
    islands.forEach(c => c.classList.toggle('ghost', !circlesLit.has(c.dataset.circle)));
    const fresh = Object.keys(first).filter(p => first[p] === y && byId[p]).map(p => byId[p].name);
    $('#tylabel').textContent = y;
    $('#tycap').textContent = `${lit.size} people · ${t.photos[i]} pictures${fresh.length ? ` · new: ${fresh.slice(0, 3).join(', ')}${fresh.length > 3 ? ` +${fresh.length - 3}` : ''}` : ''}`;
    $('#thist').querySelectorAll('rect').forEach((r, j) => r.classList.toggle('on', j === i));
  };
  let timer = null;
  const stop = () => { clearInterval(timer); timer = null; $('#tplay').innerHTML = ic('play'); };
  slider.oninput = () => { stop(); show(+slider.value); };
  $('#tall').onclick = () => { stop(); slider.value = t.years.length; show(t.years.length); };
  $('#tplay').onclick = () => {
    if (timer) return stop();
    if (+slider.value >= t.years.length - 1) slider.value = 0;
    $('#tplay').innerHTML = '<svg class="icon"><path d="M8 5v14M16 5v14"/></svg>';
    show(+slider.value);
    timer = setInterval(() => {
      if (!document.body.contains(slider)) return stop();
      if (+slider.value >= t.years.length - 1) { stop(); return; }
      slider.value = +slider.value + 1; show(+slider.value);
    }, 900);
  };
  show(t.years.length);
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
    const n = `${ids.length} ${ids.length === 1 ? 'face' : 'faces'}`;
    // answer at once: the card goes, the server catches up in the background
    const next = card.nextElementSibling, parent = card.parentNode;
    card.remove();
    GROUPS.groups = GROUPS.groups.filter(g => g.id !== card.dataset.g);
    GROUPS.total_groups = Math.max(0, GROUPS.total_groups - 1);
    if ($('#gleft')) $('#gleft').textContent = GROUPS.total_groups;
    if (OV) { OV.unknown_faces = Math.max(0, OV.unknown_faces - ids.length); shell('faces'); }
    if (OV && OV.site) { toast(`${label} · ${n} — a demo: kept for this visit, the family's graph is not changed`); return refill(); }
    toast(`${label} · ${n}`, async () => { await Promise.all(ids.map(id => api('/api/undo', {obs_id: id}))); route(); });
    try { await api('/api/answer_group', {obs_ids: ids, ...body}); }
    catch (e) { parent.insertBefore(card, next); toast(`Not saved: ${e.message}`); }
    refill();
  };
  // more cards in the background when few are left; the server regroups with the new names on its own
  let refilling = false;
  const refill = async () => {
    if (refilling || GROUPS.groups.length >= 5) return;
    refilling = true;
    try {
      const shown = new Set($$('#grouplist [data-g]').map(c => c.dataset.g));
      const g = await api('/api/face_groups');
      const fresh = g.groups.filter(x => !shown.has(x.id));
      GROUPS = {...g, groups: [...GROUPS.groups, ...fresh]};
      $('#grouplist').insertAdjacentHTML('beforeend', fresh.map(groupHtml).join(''));
    } catch (e) { /* the next answer tries again */ }
    refilling = false;
  };
  $('#grouplist').onclick = e => {
    const card = e.target.closest('[data-g]'); if (!card) return;
    const x = GROUPS.groups.find(g => g.id === card.dataset.g);
    const f = e.target.closest('.gface'); if (f) { f.classList.toggle('off'); return; }
    const b = e.target.closest('button'); if (!b || b.closest('form')) return;   // the Add button belongs to the name form
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
    const id = card.dataset.f, next = card.nextElementSibling, parent = card.parentNode;
    card.remove();
    FACES.faces = FACES.faces.filter(f => f.id !== id); FACES.total--;
    $('#facecount').textContent = `${FACES.total} faces to go`;
    if (OV) { OV.unknown_faces = Math.max(0, OV.unknown_faces - 1); shell('faces'); }
    if (OV && OV.site) return toast(`${label} — a demo: kept for this visit, the family's graph is not changed`);
    toast(label, async () => { await api('/api/undo', {obs_id: id}); route(); });
    try {
      await api('/api/answer', {obs_id: id, ...body});
      if (body.new_name) PEOPLE = await api('/api/people');
      if (FACES.faces.length < 5 && FACES.total > FACES.faces.length) { FACES = await api('/api/faces?limit=30&unclear=1'); drawFaces(); }
    } catch (e) { parent.insertBefore(card, next); toast(`Not saved: ${e.message}`); }
  };
  $('#facelist').onclick = e => {
    const card = e.target.closest('[data-f]'); if (!card) return;
    const b = e.target.closest('button'); if (!b || b.closest('form')) return;   // the Add button belongs to the name form
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
  const preset = params.get('req') || (idea === 'birthday' && other ? `A 60-second birthday film for ${en(other)}, warm and a little funny, ending with everyone together.`
    : idea === 'together' && me && other ? `A one-minute film about ${en(me)} and ${en(other)} together, from the first picture to the last.`
    : idea === 'year' && OV?.years ? `A one-minute film of my year ${OV.years[1]}, in the order it happened.` : '');
  const quick = [
    ...ps.filter(p => !p.owner).slice(0, 3).map(p => [`Birthday: ${p.name}`, `A 60-second birthday film for ${en(p)}, warm and a little funny, ending with everyone together.`]),
    me ? [`My story`, `A 90-second film of ${en(me)}'s life so far, from childhood to today.`] : null,
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
  const gone = !waiting && qs.some(q => q.answer == null) && ['failed', 'interrupted'].includes(st.status);
  return `<div class="card pad ${waiting ? 'ask' : ''}"><div class="eyebrow">${waiting ? `The crew is waiting for you · ${left} min`
      : gone ? 'These questions closed when the film stopped' : 'What the crew asked'}</div>
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
    <h1 dir="auto">${esc(st.title || 'Planning…')}</h1><p dir="auto">“${esc(st.request)}”</p>${st.error ? `<p style="color:#c92a2a">${esc(st.error)}</p>` : ''}
    ${['failed', 'interrupted'].includes(st.status) ? `<p class="small muted">${st.status === 'interrupted'
      ? 'The server restarted while this film was being made.' : 'Something went wrong while making this film.'}</p>
      <button class="btn primary" data-again="${esc(st.id)}">${ic('film')}Make it again</button>` : ''}</div></div>`;
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
    const ag = e.target.closest('[data-again]');
    if (ag) {
      ag.disabled = true;
      try { const {id} = await api(`/api/films/${enc(ag.dataset.again)}/again`, {}); location.hash = `#/film/${id}`; }
      catch (err) { ag.disabled = false; toast(err.message); }
      return;
    }
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
      if (OV && OV.site) return toast("A demo: names can't be changed in this family's graph");
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
