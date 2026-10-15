// Game Pass Filter – filtert den Game-Pass-Katalog nach Jahr, Metascore, Spielzeit, Genre, Spielmodus …

interface Game {
  id: string;
  t: string;
  img?: string;
  sq?: boolean;
  url: string;
  links?: Record<string, string>;
  ps?: string[];
  deals?: { src: string; until?: string; from?: string; via?: string }[];
  img2?: string;
  plat: string[];
  new?: boolean;
  leaving?: boolean;
  added?: string;
  genres?: string[];
  feat?: string[];
  onlineOnly?: boolean;
  onlineMax?: number;
  localMax?: number;
  y?: number;
  yx?: number;
  mc?: number;
  us?: number;
  usN?: number;
  gone?: boolean;
  mcSlug?: string;
  hMain?: number;
  hExtra?: number;
  hComp?: number;
  hltbId?: number;
  openWorld?: boolean;
  tier?: string;
  tierWhy?: string;
  tags?: string[];
  steam?: number;
  pegi?: number;
  stars?: number;
  pub?: string;
  dev?: string;
}

type HKey = 'hMain' | 'hExtra' | 'hComp';
type Tri = Record<string, 1 | -1>; // 1 = muss, -1 = darf nicht

interface State {
  q: string;
  sort: string;
  plat: string[];
  status: string[];
  year: [number | null, number | null];
  mc: [number | null, number | null];
  us: [number | null, number | null]; // User Score x10 (0–100), damit die URL ganzzahlig bleibt
  tab: 'all' | 'list';
  hKind: HKey;
  hours: [number | null, number | null];
  missing: boolean;
  genres: Tri;
  modes: string[];
  online: 'any' | 'offline' | 'onlineOnly';
  players: number;
  ow: 'any' | 'yes' | 'no';
  tier: string[];
  tags: Tri;
  tech: string[];
  pegi: number;
  stars: number;
}

const GENRES: Record<string, string> = {
  'Action & adventure': 'Action & Abenteuer',
  'Role playing': 'Rollenspiel',
  Shooter: 'Shooter',
  Simulation: 'Simulation',
  Strategy: 'Strategie',
  Platformer: 'Plattformer',
  'Family & kids': 'Familie & Kinder',
  'Racing & flying': 'Rennen & Fliegen',
  Sports: 'Sport',
  'Puzzle & trivia': 'Puzzle & Quiz',
  Fighting: 'Kampfspiel',
  'Card & board': 'Karten & Brett',
  'Multi-player Online Battle Arena': 'MOBA',
  Party: 'Party',
  'Interactive story': 'Interaktive Geschichte',
  Arcade: 'Arcade',
  Classics: 'Klassiker',
  Music: 'Musik',
  Other: 'Sonstiges',
};
const SUBS: Record<string, string> = {
  console: 'Konsole',
  pc: 'PC',
  cloud: 'Cloud',
  ea: 'EA Play',
  lunaPrime: 'Luna (Prime)',
  lunaPremium: 'Luna Premium',
  netflixMobile: 'Netflix (Handy)',
  netflixTV: 'Netflix (TV)',
  psEssential: 'PS Plus Essential',
  psExtra: 'PS Plus Extra',
  psPremium: 'PS Plus Premium',
};
const FREE: Record<string, string> = {
  epicFree: 'Epic: jetzt gratis',
  epicSoon: 'Epic: bald gratis',
  primeClaim: 'Prime: zum Abholen',
  primeSoon: 'Prime: bald abholbar',
};
const PLATS: Record<string, string> = { ...SUBS, ...FREE };
const PLAT_SHORT: Record<string, string> = {
  lunaPrime: 'Luna',
  lunaPremium: 'Luna Premium',
  netflixMobile: 'Netflix Handy',
  netflixTV: 'Netflix TV',
  epicFree: 'Epic gratis',
  epicSoon: 'Epic bald gratis',
  primeClaim: 'Prime-Abholspiel',
  primeSoon: 'Prime bald',
};
const LINK_LABELS: Record<string, string> = { luna: 'Luna', netflix: 'Netflix', playstation: 'PlayStation', epic: 'Epic', prime: 'Prime' };
const STATUS: Record<string, string> = { new: 'Neu im Game Pass', leaving: 'Verlässt bald' };
const MODES: Record<string, string> = {
  single: 'Einzelspieler',
  onlineMP: 'Online-Multiplayer',
  onlineCoop: 'Online-Koop',
  localMP: 'Lokaler Multiplayer',
  localCoop: 'Lokaler Koop',
  splitscreen: 'Splitscreen',
  crossplay: 'Crossplay',
};
const TECH: Record<string, string> = {
  seriesOptimized: 'Optimiert für Series X|S',
  playAnywhere: 'Play Anywhere',
  '4k': '4K',
  '120fps': '120 FPS',
  raytracing: 'Raytracing',
  mouseKeyboard: 'Maus & Tastatur (Konsole)',
  cloudSaves: 'Cloud-Speicherstände',
};
const TIERS: Record<string, string> = { AAA: 'AAA', AA: 'AA', Indie: 'Indie' };
const H_KINDS: Record<HKey, string> = { hMain: 'Story', hExtra: 'Story + Extras', hComp: '100 %' };
const H_STEPS = [0, 1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50, 60, 80, 100, 150];
const SORTS: Record<string, string> = {
  mc: 'Metascore',
  us: 'User Score',
  listAdded: 'Zuletzt auf meine Liste',
  year: 'Neueste zuerst',
  yearAsc: 'Älteste zuerst',
  hAsc: 'Kürzeste Spielzeit',
  hDesc: 'Längste Spielzeit',
  stars: 'Xbox-Bewertung',
  added: 'Neu im Game Pass',
  deadline: 'Gratis-Frist läuft ab',
  title: 'Titel A–Z',
};

const $ = <T extends HTMLElement = HTMLElement>(sel: string) => document.querySelector(sel) as T;
const esc = (s: string) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
const fmtH = (h: number) => (h < 10 ? h.toFixed(1).replace('.', ',').replace(',0', '') : String(Math.round(h)));

let games: Game[] = [];
let YEAR_MIN = 1980;
const YEAR_MAX = new Date().getFullYear();

function defaults(): State {
  return {
    q: '',
    sort: 'mc',
    plat: [],
    status: [],
    year: [null, null],
    mc: [null, null],
    us: [null, null],
    tab: 'all',
    hKind: 'hMain',
    hours: [null, null],
    missing: false,
    genres: {},
    modes: [],
    online: 'any',
    players: 0,
    ow: 'any',
    tier: [],
    tags: {},
    tech: [],
    pegi: 0,
    stars: 0,
  };
}
let S = defaults();

// ---------- URL <-> Zustand ----------

function triToStr(t: Tri) {
  return Object.entries(t).map(([k, v]) => (v < 0 ? '-' : '') + k).join('|');
}
function strToTri(s: string | null): Tri {
  const t: Tri = {};
  for (const x of (s || '').split('|').filter(Boolean)) {
    if (x.startsWith('-')) t[x.slice(1)] = -1;
    else t[x] = 1;
  }
  return t;
}
const rng = (r: [number | null, number | null]) => (r[0] ?? '') + '-' + (r[1] ?? '');
function parseRng(s: string | null): [number | null, number | null] {
  const m = (s || '').match(/^(\d*)-(\d*)$/);
  if (!m) return [null, null];
  return [m[1] ? +m[1] : null, m[2] ? +m[2] : null];
}

function saveUrl() {
  const d = defaults();
  const p = new URLSearchParams();
  if (S.q) p.set('q', S.q);
  if (S.sort !== d.sort) p.set('sort', S.sort);
  if (S.plat.length) p.set('plat', S.plat.join('|'));
  if (S.status.length) p.set('status', S.status.join('|'));
  if (S.year.some((x) => x !== null)) p.set('year', rng(S.year));
  if (S.mc.some((x) => x !== null)) p.set('mc', rng(S.mc));
  if (S.us.some((x) => x !== null)) p.set('us', rng(S.us));
  if (S.tab === 'list') p.set('tab', 'list');
  if (S.hKind !== d.hKind) p.set('hk', S.hKind);
  if (S.hours.some((x) => x !== null)) p.set('h', rng(S.hours));
  if (S.missing) p.set('missing', '1');
  if (Object.keys(S.genres).length) p.set('genre', triToStr(S.genres));
  if (S.modes.length) p.set('mode', S.modes.join('|'));
  if (S.online !== 'any') p.set('online', S.online);
  if (S.players) p.set('players', String(S.players));
  if (S.ow !== 'any') p.set('ow', S.ow);
  if (S.tier.length) p.set('tier', S.tier.join('|'));
  if (Object.keys(S.tags).length) p.set('tags', triToStr(S.tags));
  if (S.tech.length) p.set('tech', S.tech.join('|'));
  if (S.pegi) p.set('pegi', String(S.pegi));
  if (S.stars) p.set('stars', String(S.stars));
  const qs = p.toString();
  history.replaceState(null, '', qs ? '?' + qs : location.pathname);
}

function loadUrl() {
  const p = new URLSearchParams(location.search);
  const list = (k: string) => (p.get(k) || '').split('|').filter(Boolean);
  const s = defaults();
  s.q = p.get('q') || '';
  if (p.get('sort') && SORTS[p.get('sort')!]) s.sort = p.get('sort')!;
  s.plat = list('plat');
  s.status = list('status');
  s.year = parseRng(p.get('year'));
  s.mc = parseRng(p.get('mc'));
  s.us = parseRng(p.get('us'));
  s.tab = p.get('tab') === 'list' ? 'list' : 'all';
  if (p.get('hk') && p.get('hk')! in H_KINDS) s.hKind = p.get('hk') as HKey;
  s.hours = parseRng(p.get('h'));
  s.missing = p.get('missing') === '1';
  s.genres = strToTri(p.get('genre'));
  s.modes = list('mode');
  const on = p.get('online');
  if (on === 'offline' || on === 'onlineOnly') s.online = on;
  s.players = +(p.get('players') || 0);
  const ow = p.get('ow');
  if (ow === 'yes' || ow === 'no') s.ow = ow;
  s.tier = list('tier');
  s.tags = strToTri(p.get('tags'));
  s.tech = list('tech');
  s.pegi = +(p.get('pegi') || 0);
  s.stars = +(p.get('stars') || 0);
  S = s;
}

// ---------- Filtern ----------

const players = (g: Game) => Math.max(g.onlineMax || 0, g.localMax || 0) || undefined;

function inRange(v: number | undefined, r: [number | null, number | null]) {
  if (r[0] === null && r[1] === null) return true;
  if (v === undefined) return S.missing;
  return (r[0] === null || v >= r[0]) && (r[1] === null || v <= r[1]);
}

function matchTri(have: string[] | undefined, t: Tri, mode: 'any' | 'all') {
  const inc = Object.keys(t).filter((k) => t[k] > 0);
  const exc = Object.keys(t).filter((k) => t[k] < 0);
  const h = new Set(have || []);
  if (exc.some((k) => h.has(k))) return false;
  if (!inc.length) return true;
  return mode === 'any' ? inc.some((k) => h.has(k)) : inc.every((k) => h.has(k));
}

function matches(g: Game) {
  if (S.q) {
    const q = S.q.toLowerCase();
    if (!g.t.toLowerCase().includes(q) && !(g.dev || '').toLowerCase().includes(q) && !(g.pub || '').toLowerCase().includes(q))
      return false;
  }
  if (S.plat.length && !S.plat.some((p) => g.plat.includes(p))) return false;
  if (S.status.length && !S.status.some((s) => (g as unknown as Record<string, unknown>)[s])) return false;
  if (!inRange(g.y, S.year)) return false;
  if (!inRange(g.mc, S.mc)) return false;
  if (!inRange(g.us !== undefined ? g.us * 10 : undefined, S.us)) return false;
  if (!inRange(g[S.hKind], S.hours)) return false;
  if (!matchTri(g.genres, S.genres, 'any')) return false;
  if (S.modes.length && !S.modes.every((m) => g.feat?.includes(m))) return false;
  if (S.online === 'offline' && g.onlineOnly) return false;
  if (S.online === 'onlineOnly' && !g.onlineOnly) return false;
  if (S.players) {
    const n = players(g);
    if (n === undefined ? !S.missing : n < S.players) return false;
  }
  if (S.ow !== 'any') {
    if (g.openWorld === undefined) {
      if (!S.missing) return false;
    } else if (g.openWorld !== (S.ow === 'yes')) return false;
  }
  if (S.tier.length && !(g.tier ? S.tier.includes(g.tier) : S.missing)) return false;
  if (!matchTri(g.tags, S.tags, 'all')) return false;
  if (S.tech.length && !S.tech.every((m) => g.feat?.includes(m))) return false;
  if (S.pegi && (g.pegi ?? 99) > S.pegi) return false;
  if (S.stars && (g.stars ?? 0) < S.stars) return false;
  return true;
}

function sortGames(list: Game[]) {
  const by = (f: (g: Game) => number | undefined, dir: 1 | -1) => (a: Game, b: Game) => {
    const x = f(a), y = f(b);
    if (x === undefined && y === undefined) return a.t.localeCompare(b.t, 'de');
    if (x === undefined) return 1;
    if (y === undefined) return -1;
    return (x - y) * dir || a.t.localeCompare(b.t, 'de');
  };
  const cmp: Record<string, (a: Game, b: Game) => number> = {
    mc: by((g) => g.mc, -1),
    us: by((g) => g.us, -1),
    listAdded: by((g) => myList.get(g.id)?.at, -1),
    year: by((g) => g.y, -1),
    yearAsc: by((g) => g.y, 1),
    hAsc: by((g) => g[S.hKind], 1),
    hDesc: by((g) => g[S.hKind], -1),
    stars: by((g) => g.stars, -1),
    added: by((g) => (g.new ? 1e9 : 0) + (g.added ? Date.parse(g.added) / 864e5 : 0), -1),
    deadline: by((g) => {
      const d = (g.deals || []).map((x) => x.until || x.from).filter(Boolean).sort()[0];
      return d ? Date.parse(d) : undefined;
    }, 1),
    title: (a, b) => a.t.localeCompare(b.t, 'de'),
  };
  return list.sort(cmp[S.sort] || cmp.mc);
}

// ---------- Kacheln ----------

type Col = 'mc' | 'y' | 'h' | 'tier' | 'plat' | 'genres' | 'modes' | 'online' | 'players' | 'ow' | 'tags' | 'tech' | 'pegi' | 'stars' | 'added';

function visibleCols(): Col[] {
  const c = new Set<Col>();
  const sortCol: Record<string, Col> = { mc: 'mc', us: 'mc', year: 'y', yearAsc: 'y', hAsc: 'h', hDesc: 'h', stars: 'stars', added: 'added' };
  if (S.mc.some((x) => x !== null) || S.us.some((x) => x !== null)) c.add('mc');
  if (S.year.some((x) => x !== null)) c.add('y');
  if (S.hours.some((x) => x !== null)) c.add('h');
  if (sortCol[S.sort]) c.add(sortCol[S.sort]);
  if (S.plat.length) c.add('plat');
  if (Object.values(S.genres).some((v) => v > 0)) c.add('genres');
  if (S.modes.length) c.add('modes');
  if (S.online !== 'any') c.add('online');
  if (S.players) c.add('players');
  if (S.ow !== 'any') c.add('ow');
  if (S.tier.length) c.add('tier');
  if (Object.values(S.tags).some((v) => v > 0)) c.add('tags');
  if (S.tech.length) c.add('tech');
  if (S.pegi) c.add('pegi');
  if (S.stars) c.add('stars');
  // ohne aktive Filter: die drei Kernwerte
  if (c.size <= 1) ['mc', 'y', 'h'].forEach((x) => c.add(x as Col));
  const order: Col[] = ['mc', 'y', 'h', 'tier', 'stars', 'players', 'ow', 'online', 'modes', 'genres', 'tags', 'tech', 'plat', 'pegi', 'added'];
  return order.filter((x) => c.has(x));
}

function val(html: string, title: string, na = false, wrap = false) {
  return `<span class="val${na ? ' na' : ''}${wrap ? ' wrap' : ''}" title="${esc(title)}">${html}</span>`;
}

function cellHtml(g: Game, col: Col): string {
  switch (col) {
    case 'mc': {
      const mcLink = (html: string, path = '') =>
        g.mcSlug ? `<a href="https://www.metacritic.com/game/${g.mcSlug}/${path}" target="_blank" rel="noopener">${html}</a>` : html;
      const meta =
        g.mc === undefined
          ? val('MC –', 'Kein Metascore', true)
          : val(mcLink(`<span class="mc ${g.mc >= 75 ? 'good' : g.mc >= 50 ? 'mid' : 'bad'}">${g.mc}</span>`), 'Metascore (Kritiker)');
      const user =
        g.us === undefined
          ? g.mc !== undefined
            ? val('<span class="us na">–</span>', 'Kein User Score', true)
            : ''
          : val(
              mcLink(`<span class="us ${g.us >= 7.5 ? 'good' : g.us >= 5 ? 'mid' : 'bad'}">${g.us.toFixed(1).replace('.', ',')}</span>`, 'user-reviews/'),
              `User Score (Metacritic)${g.usN ? ` – ${g.usN.toLocaleString('de-DE')} Bewertungen` : ''}`,
            );
      return meta + user;
    }
    case 'y':
      return g.y ? val(String(g.y), g.yx && g.yx !== g.y ? `Erschienen ${g.y}, auf Xbox ${g.yx}` : 'Erscheinungsjahr') : val('Jahr –', 'Unbekannt', true);
    case 'h': {
      const h = g[S.hKind];
      const label = H_KINDS[S.hKind];
      if (h === undefined) return val('⏱ –', `Keine HowLongToBeat-Daten (${label})`, true);
      const txt = `⏱ ${fmtH(h)} Std.`;
      return val(
        g.hltbId ? `<a href="https://howlongtobeat.com/game/${g.hltbId}" target="_blank" rel="noopener">${txt}</a>` : txt,
        `HowLongToBeat – ${label}`,
      );
    }
    case 'stars':
      return g.stars ? val(`★ ${g.stars.toFixed(1).replace('.', ',')}`, 'Xbox-Nutzerbewertung') : val('★ –', 'Keine Bewertung', true);
    case 'players': {
      const n = players(g);
      return n ? val(`👥 bis ${n}`, `Online bis ${g.onlineMax ?? '–'}, lokal bis ${g.localMax ?? '–'}`) : val('👥 –', 'Spieleranzahl unbekannt', true);
    }
    case 'ow':
      return g.openWorld === undefined ? val('Open World ?', 'Unbekannt', true) : val(g.openWorld ? 'Open World' : 'keine Open World', 'Steam-Tags / Metacritic');
    case 'tier':
      return g.tier ? val(g.tier, 'Geschätzte Produktionsgröße: ' + (g.tierWhy || '')) : val('AAA/AA ?', 'Zu wenig Anhaltspunkte', true);
    case 'online':
      return val(g.onlineOnly ? 'Nur online' : 'Offline spielbar', 'Online/Offline');
    case 'modes':
      return S.modes.map((m) => val(MODES[m], 'Spielmodus')).join('');
    case 'genres':
      return (g.genres || []).filter((x) => S.genres[x] > 0).map((x) => val(GENRES[x] || x, 'Genre')).join('');
    case 'tags':
      return Object.keys(S.tags).filter((k) => S.tags[k] > 0).map((k) => val('#' + k, 'Steam-Tag')).join('');
    case 'tech':
      return S.tech.map((m) => val(TECH[m], 'Technik')).join('');
    case 'plat':
      return val(
        g.plat
          // bei Stufen-Abos nur die niedrigste nennen (Premium enthält Extra, Extra enthält Essential)
          .filter((p) => !(p === 'lunaPremium' && g.plat.includes('lunaPrime')))
          .filter((p) => !(p === 'psPremium' && g.plat.includes('psExtra')) && !(p === 'psExtra' && g.plat.includes('psEssential')))
          .map((p) => {
            const via = p.startsWith('prime') ? g.deals?.find((d) => d.src === 'prime')?.via : undefined;
            const dev = p.startsWith('ps') && g.ps?.length ? g.ps.join('/') : undefined;
            return (PLAT_SHORT[p] || PLATS[p]) + (via ? ` (${via})` : dev ? ` (${dev})` : '');
          })
          .join(' · '),
        g.plat.map((p) => PLATS[p]).join(', '),
        false,
        true,
      );
    case 'pegi':
      return g.pegi !== undefined ? val(`ab ${g.pegi}`, 'Altersfreigabe (PEGI/USK)') : val('ab ?', 'Keine Angabe', true);
    case 'added':
      return g.new
        ? val('neu', 'Zuletzt hinzugefügt')
        : g.added
          ? val('seit ' + new Date(g.added).toLocaleDateString('de-DE'), 'In dieser Liste seit')
          : '';
  }
}

function cardHtml(g: Game, cols: Col[]) {
  const src = g.img && g.img.includes('s-microsoft.com') ? `${g.img}?w=${g.sq ? 320 : 300}` : g.img;
  // Ersatzbild, falls das Steam-Hochformat-Cover fehlt
  const fallback = g.img2 ? ` onerror="this.onerror=null;this.src='${g.img2}';this.parentNode.classList.add('sq')"` : '';
  const img = src ? `<img src="${src}" alt="" loading="lazy" decoding="async"${fallback}>` : `<span class="noimg">${esc(g.t)}</span>`;
  // Wohin führt das Cover? Xbox, sonst die erste andere Plattform; die übrigen als kleine Links
  const target = Object.entries(g.links || {}).find(([, u]) => u === g.url)?.[0];
  const others = Object.entries(g.links || {}).filter(([, u]) => u !== g.url);
  const links = others.length
    ? `<div class="more-links">auch: ${others
        .map(([k, u]) => `<a href="${u}" target="_blank" rel="noopener">${LINK_LABELS[k] || k} ↗</a>`)
        .join(' · ')}</div>`
    : '';
  const dm = (d?: string) => (d ? new Date(d).toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit' }) : '');
  const dealBadges = (g.deals || []).map((d) =>
    d.src === 'epic'
      ? `<span class="badge free" title="Gratis im Epic Games Store">${d.until ? 'GRATIS BIS ' + dm(d.until) : 'GRATIS AB ' + dm(d.from)}</span>`
      : `<span class="badge prime" title="Mit Prime abholen${d.via ? ' über ' + esc(d.via) : ''}">PRIME${d.until ? ' BIS ' + dm(d.until) : d.from ? ' AB ' + dm(d.from) : ''}</span>`,
  );
  const badges = [
    g.new ? '<span class="badge new">NEU</span>' : '',
    g.leaving ? '<span class="badge leaving">VERLÄSST BALD</span>' : '',
    g.gone ? '<span class="badge leaving">NICHT MEHR IM ANGEBOT</span>' : '',
    target === 'luna' ? '<span class="badge luna">LUNA</span>' : '',
    target === 'netflix' ? '<span class="badge netflix">NETFLIX</span>' : '',
    target === 'playstation' ? '<span class="badge ps">PS PLUS</span>' : '',
    ...dealBadges,
  ]
    .filter(Boolean)
    .join('');
  const where = target ? { luna: 'bei Amazon Luna', netflix: 'bei Netflix', playstation: 'im PlayStation Store', epic: 'im Epic Games Store', prime: 'bei Prime' }[target] : 'im Xbox Store';
  const on = myList.has(g.id);
  const addBtn = `<button class="add${on ? ' on' : ''}" data-id="${esc(g.id)}" title="${on ? 'Von meiner Liste entfernen' : 'Zu meiner Liste hinzufügen'}" aria-label="${on ? 'Von meiner Liste entfernen' : 'Zu meiner Liste hinzufügen'}">${on ? '✓' : '+'}</button>`;
  return `<article class="card">${addBtn}
    <a class="cover${g.sq ? ' sq' : ''}" href="${g.url}" target="_blank" rel="noopener" title="${esc(g.t)} ${where} öffnen">${img}<div class="badges">${badges}</div></a>
    <div class="title" title="${esc(g.t)}${g.dev ? ' – ' + esc(g.dev) : ''}">${esc(g.t)}</div>
    <div class="vals">${cols.map((c) => cellHtml(g, c)).join('')}</div>${links}
  </article>`;
}

let renderToken = 0;
function render() {
  saveUrl();
  const inList = S.tab === 'list';
  const base = inList ? listGames() : games;
  const list = sortGames(base.filter(matches));
  const cols = visibleCols();
  $('#count').innerHTML = inList
    ? `<b>${list.length}</b> von ${base.length} Spielen auf deiner Liste`
    : `<b>${list.length}</b> von ${games.length} Spielen`;
  const empty = $('#empty');
  empty.hidden = list.length > 0;
  empty.textContent = inList && !base.length
    ? 'Deine Liste ist noch leer. Mit dem + oben rechts an einem Cover setzt du Spiele darauf.'
    : 'Keine Spiele passen zu diesen Filtern.';
  document.querySelectorAll<HTMLButtonElement>('.tabs button').forEach((b) => b.classList.toggle('on', b.dataset.tab === S.tab));
  $('#listCount').textContent = myList.size ? String(myList.size) : '';
  $('#shareList').hidden = !inList || !myList.size;
  const grid = $('#grid');
  // in Häppchen rendern, damit die Seite bei 800 Kacheln flüssig bleibt
  const token = ++renderToken;
  grid.innerHTML = list.slice(0, 120).map((g) => cardHtml(g, cols)).join('');
  let i = 120;
  const more = () => {
    if (token !== renderToken || i >= list.length) return;
    grid.insertAdjacentHTML('beforeend', list.slice(i, i + 200).map((g) => cardHtml(g, cols)).join(''));
    i += 200;
    requestAnimationFrame(more);
  };
  requestAnimationFrame(more);
  renderActiveChips();
  syncControls();
}

// ---------- Meine Liste (nur in diesem Browser gespeichert) ----------

interface Saved {
  id: string;
  t: string;
  img?: string;
  sq?: boolean;
  url: string;
  at: number;
}
const LIST_KEY = 'gamepass-filter.myList';
let myList = new Map<string, Saved>();

function loadList() {
  try {
    const arr = JSON.parse(localStorage.getItem(LIST_KEY) || '[]') as Saved[];
    myList = new Map(arr.map((x) => [x.id, x]));
  } catch {
    myList = new Map();
  }
}
function saveList() {
  try {
    localStorage.setItem(LIST_KEY, JSON.stringify([...myList.values()]));
  } catch {
    /* privates Fenster o. Ä.: Liste gilt dann nur bis zum Neuladen */
  }
}
function addToList(g: Game) {
  myList.set(g.id, { id: g.id, t: g.t, img: g.img, sq: g.sq, url: g.url, at: Date.now() });
}

const byId = () => new Map(games.map((g) => [g.id, g]));
/** Spiele der Liste; was nicht mehr im Katalog ist, bleibt mit gespeichertem Titel/Cover sichtbar. */
function listGames(): Game[] {
  const idx = byId();
  return [...myList.values()].map((x) => idx.get(x.id) || { id: x.id, t: x.t, img: x.img, sq: x.sq, url: x.url, plat: [], gone: true });
}

function toggleList(id: string, btn: HTMLButtonElement) {
  if (myList.has(id)) myList.delete(id);
  else {
    const g = byId().get(id);
    if (g) addToList(g);
  }
  saveList();
  if (S.tab === 'list') return render();
  const on = myList.has(id);
  btn.classList.toggle('on', on);
  btn.textContent = on ? '✓' : '+';
  btn.title = on ? 'Von meiner Liste entfernen' : 'Zu meiner Liste hinzufügen';
  $('#listCount').textContent = myList.size ? String(myList.size) : '';
}

/** Liste per Link auf ein anderes Gerät übertragen */
async function shareList() {
  const url = `${location.origin}${location.pathname}?tab=list&import=${encodeURIComponent([...myList.keys()].join('|'))}`;
  try {
    await navigator.clipboard.writeText(url);
    alert('Link kopiert. Öffne ihn auf dem anderen Gerät, dann werden die Spiele dort zur Liste hinzugefügt.');
  } catch {
    prompt('Diesen Link auf dem anderen Gerät öffnen:', url);
  }
}
function importFromUrl() {
  const p = new URLSearchParams(location.search);
  const ids = (p.get('import') || '').split('|').filter(Boolean);
  if (!ids.length) return;
  const idx = byId();
  const fresh = ids.filter((id) => idx.has(id) && !myList.has(id));
  if (fresh.length && confirm(`${fresh.length} Spiele zu deiner Liste hinzufügen?`)) {
    fresh.forEach((id) => addToList(idx.get(id)!));
    saveList();
  }
  p.delete('import');
  history.replaceState(null, '', p.toString() ? '?' + p : location.pathname);
}

// ---------- Filterleiste ----------

interface Ctl {
  sync: () => void;
}
const controls: Ctl[] = [];

function group(title: string, body: HTMLElement | HTMLElement[], reset?: () => void, hint?: string) {
  const g = document.createElement('section');
  g.className = 'fgroup';
  const h = document.createElement('h3');
  h.textContent = title;
  if (reset) {
    const b = document.createElement('button');
    b.className = 'reset';
    b.textContent = 'zurücksetzen';
    b.onclick = () => {
      reset();
      render();
    };
    h.append(b);
  }
  g.append(h, ...(Array.isArray(body) ? body : [body]));
  if (hint) {
    const p = document.createElement('p');
    p.className = 'hint';
    p.textContent = hint;
    g.append(p);
  }
  return g;
}

function chipList(opts: Record<string, string>, get: () => string[], set: (v: string[]) => void, counts?: Record<string, number>) {
  const wrap = document.createElement('div');
  wrap.className = 'chips';
  const btns: [string, HTMLButtonElement][] = [];
  for (const [k, label] of Object.entries(opts)) {
    if (counts && !counts[k]) continue;
    const b = document.createElement('button');
    b.className = 'chip';
    b.textContent = label;
    if (counts) b.title = `${counts[k]} Spiele`;
    b.onclick = () => {
      const v = get();
      set(v.includes(k) ? v.filter((x) => x !== k) : [...v, k]);
      render();
    };
    btns.push([k, b]);
    wrap.append(b);
  }
  controls.push({ sync: () => btns.forEach(([k, b]) => b.classList.toggle('on', get().includes(k))) });
  return wrap;
}

/** Chips mit drei Zuständen: aus → muss → darf nicht → aus */
function triChips(opts: Record<string, string>, get: () => Tri, counts: Record<string, number>, small = false) {
  const wrap = document.createElement('div');
  wrap.className = 'chips' + (small ? ' popular-tags' : '');
  const btns: [string, HTMLButtonElement][] = [];
  for (const [k, label] of Object.entries(opts)) {
    const b = document.createElement('button');
    b.className = 'chip';
    b.textContent = label;
    b.title = `${counts[k] || 0} Spiele · Klick: einschließen, nochmal: ausschließen`;
    b.onclick = () => {
      const t = get();
      if (!t[k]) t[k] = 1;
      else if (t[k] > 0) t[k] = -1;
      else delete t[k];
      render();
    };
    btns.push([k, b]);
    wrap.append(b);
  }
  controls.push({
    sync: () =>
      btns.forEach(([k, b]) => {
        b.classList.toggle('on', get()[k] > 0);
        b.classList.toggle('off', get()[k] < 0);
      }),
  });
  return wrap;
}

function seg<T extends string>(opts: Record<T, string>, get: () => T, set: (v: T) => void) {
  const wrap = document.createElement('div');
  wrap.className = 'seg';
  const btns: [T, HTMLButtonElement][] = [];
  for (const [k, label] of Object.entries(opts) as [T, string][]) {
    const b = document.createElement('button');
    b.textContent = label;
    b.onclick = () => {
      set(k);
      render();
    };
    btns.push([k, b]);
    wrap.append(b);
  }
  controls.push({ sync: () => btns.forEach(([k, b]) => b.classList.toggle('on', get() === k)) });
  return wrap;
}

/** Doppel-Schieberegler über eine Werteliste; Endpunkte bedeuten "offen" (null). */
function rangeSlider(steps: number[], get: () => [number | null, number | null], set: (r: [number | null, number | null]) => void, fmt: (v: number, end: boolean) => string) {
  const box = document.createElement('div');
  box.innerHTML = `<div class="range"><div class="track"></div><div class="fill"></div>
    <input type="range" min="0" max="${steps.length - 1}" step="1" aria-label="von">
    <input type="range" min="0" max="${steps.length - 1}" step="1" aria-label="bis"></div>
    <div class="range-vals"><b></b><b></b></div>`;
  const [a, b] = Array.from(box.querySelectorAll('input')) as HTMLInputElement[];
  const fill = box.querySelector('.fill') as HTMLElement;
  const [la, lb] = Array.from(box.querySelectorAll('.range-vals b')) as HTMLElement[];
  const last = steps.length - 1;
  const idx = (v: number | null, dflt: number) => {
    if (v === null) return dflt;
    let best = 0;
    steps.forEach((s, i) => {
      if (Math.abs(s - v) < Math.abs(steps[best] - v)) best = i;
    });
    return best;
  };
  const show = (i: number, j: number) => {
    fill.style.left = (i / last) * 100 + '%';
    fill.style.width = ((j - i) / last) * 100 + '%';
    la.textContent = fmt(steps[i], i === 0);
    lb.textContent = fmt(steps[j], j === last);
  };
  const onInput = (e: Event) => {
    let i = +a.value, j = +b.value;
    if (i > j) {
      if (e.target === a) a.value = String((i = j));
      else b.value = String((j = i));
    }
    show(i, j);
  };
  const commit = () => {
    const i = +a.value, j = +b.value;
    set([i === 0 ? null : steps[i], j === last ? null : steps[j]]);
    render();
  };
  a.oninput = b.oninput = onInput;
  a.onchange = b.onchange = commit;
  controls.push({
    sync: () => {
      const [lo, hi] = get();
      const i = idx(lo, 0), j = idx(hi, last);
      a.value = String(i);
      b.value = String(j);
      // der obere Regler liegt oben, außer beide stehen ganz rechts
      a.style.zIndex = i === last ? '3' : '1';
      b.style.zIndex = '2';
      show(i, j);
    },
  });
  return box;
}

function selectEl(opts: [string | number, string][], get: () => string | number, set: (v: string) => void) {
  const s = document.createElement('select');
  s.innerHTML = opts.map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join('');
  s.onchange = () => {
    set(s.value);
    render();
  };
  controls.push({ sync: () => (s.value = String(get())) });
  return s;
}

function row(label: string, el: HTMLElement) {
  const r = document.createElement('label');
  r.className = 'row';
  r.append(label, el);
  return r;
}

function countBy(f: (g: Game) => string[] | undefined) {
  const c: Record<string, number> = {};
  for (const g of games) for (const k of f(g) || []) c[k] = (c[k] || 0) + 1;
  return c;
}

function buildFilters() {
  const F = $('#filters');
  const close = document.createElement('button');
  close.className = 'drawer-close chip';
  close.textContent = 'Fertig';
  close.onclick = () => document.body.classList.remove('filters-open');
  F.append(close);

  const years = Array.from({ length: YEAR_MAX - YEAR_MIN + 1 }, (_, i) => YEAR_MIN + i);
  const mcs = Array.from({ length: 21 }, (_, i) => i * 5);

  F.append(
    group('Plattform / Abo', chipList(SUBS, () => S.plat, (v) => (S.plat = v), countBy((g) => g.plat)), () => (S.plat = S.plat.filter((p) => !(p in SUBS)))),
    group(
      'Gratis zum Behalten',
      chipList(FREE, () => S.plat, (v) => (S.plat = v), countBy((g) => g.plat)),
      () => (S.plat = S.plat.filter((p) => !(p in FREE))),
      'Wöchentliche Epic-Geschenke und monatliche Prime-Spiele – nur bis zur Frist abholbar. „Bald“ = von Epic bzw. Amazon schon angekündigt.',
    ),
    group('Status', chipList(STATUS, () => S.status, (v) => (S.status = v), countBy((g) => [g.new ? 'new' : '', g.leaving ? 'leaving' : ''])), () => (S.status = [])),
    group('Erscheinungsjahr', rangeSlider(years, () => S.year, (r) => (S.year = r), (v, end) => (end ? (v === YEAR_MIN ? 'alle' : 'heute') : String(v))), () => (S.year = [null, null])),
    group('Metascore', rangeSlider(mcs, () => S.mc, (r) => (S.mc = r), (v, end) => (end ? (v === 0 ? '0' : '100') : String(v))), () => (S.mc = [null, null])),
    group(
      'User Score (Metacritic)',
      rangeSlider(Array.from({ length: 21 }, (_, i) => i * 5), () => S.us, (r) => (S.us = r), (v) => (v / 10).toFixed(1).replace('.', ',')),
      () => (S.us = [null, null]),
      'Bewertung der Spieler auf Metacritic, 0–10',
    ),
    group(
      'Spielzeit (HowLongToBeat)',
      [
        seg(H_KINDS, () => S.hKind, (v) => (S.hKind = v)),
        (() => {
          const r = rangeSlider(H_STEPS, () => S.hours, (x) => (S.hours = x), (v, end) => (end && v > 0 ? `${v}+ Std.` : `${v} Std.`));
          r.style.marginTop = '10px';
          return r;
        })(),
      ],
      () => (S.hours = [null, null]),
    ),
  );

  const missing = document.createElement('label');
  missing.className = 'row';
  missing.innerHTML = '<input type="checkbox"> Spiele ohne Angabe trotzdem zeigen';
  const cb = missing.querySelector('input')!;
  cb.onchange = () => {
    S.missing = cb.checked;
    render();
  };
  controls.push({ sync: () => (cb.checked = S.missing) });
  F.append(group('Fehlende Daten', missing, undefined, 'Gilt für Jahr, Metascore, User Score, Spielzeit, Spieleranzahl, Produktion und Open World, sobald dort gefiltert wird.'));

  const gc = countBy((g) => g.genres);
  const genreOpts = Object.fromEntries(Object.entries(GENRES).filter(([k]) => gc[k]));
  F.append(group('Genre', triChips(genreOpts, () => S.genres, gc), () => (S.genres = {}), 'Grün = eines davon, rot = ausschließen'));

  F.append(
    group(
      'Spielmodus',
      [
        chipList(MODES, () => S.modes, (v) => (S.modes = v), countBy((g) => g.feat)),
        row('Online / Offline', selectEl([['any', 'egal'], ['offline', 'offline spielbar'], ['onlineOnly', 'reines Online-Spiel']], () => S.online, (v) => (S.online = v as State['online']))),
        row('Spieler', selectEl([[0, 'egal'], [2, 'mind. 2'], [4, 'mind. 4'], [8, 'mind. 8'], [16, 'mind. 16'], [32, 'mind. 32']], () => S.players, (v) => (S.players = +v))),
      ],
      () => {
        S.modes = [];
        S.online = 'any';
        S.players = 0;
      },
    ),
    group(
      'Produktion',
      chipList(TIERS, () => S.tier, (v) => (S.tier = v), countBy((g) => (g.tier ? [g.tier] : []))),
      () => (S.tier = []),
      'Geschätzt aus Publisher, Steam-Tag „Indie“, Zahl der Kritiken und Steam-Preis – es gibt kein offizielles Label. Begründung im Tooltip am Wert.',
    ),
    group('Open World', seg({ any: 'egal', yes: 'ja', no: 'nein' } as Record<State['ow'], string>, () => S.ow, (v) => (S.ow = v)), undefined, 'Laut Steam-Tags bzw. Metacritic-Genre'),
  );

  // Steam-Tags: Freitext mit Vorschlägen + häufigste als Chips
  const tc = countBy((g) => g.tags);
  const allTags = Object.keys(tc).sort((a, b) => tc[b] - tc[a]);
  const popular = allTags.filter((t) => !['Singleplayer', 'Multiplayer', 'Open World', 'Co-op', 'Online Co-Op'].includes(t)).slice(0, 30);
  const tagBox = document.createElement('div');
  tagBox.innerHTML = `<input class="tag-input" list="tagList" placeholder="Tag suchen, z. B. Roguelike …"><datalist id="tagList">${allTags
    .map((t) => `<option value="${esc(t)}">${tc[t]} Spiele</option>`)
    .join('')}</datalist><div class="chips tag-chips"></div>`;
  const tagInput = tagBox.querySelector('input')!;
  const tagChips = tagBox.querySelector('.tag-chips') as HTMLElement;
  tagInput.onchange = () => {
    const v = allTags.find((t) => t.toLowerCase() === tagInput.value.trim().toLowerCase());
    if (v) {
      S.tags[v] = 1;
      tagInput.value = '';
      render();
    }
  };
  controls.push({
    sync: () => {
      const extra = Object.keys(S.tags).filter((t) => !popular.includes(t));
      tagChips.innerHTML = extra.map((t) => `<button class="chip ${S.tags[t] > 0 ? 'on' : 'off'}" data-t="${esc(t)}">${esc(t)}</button>`).join('');
      tagChips.querySelectorAll('button').forEach((b) => {
        b.onclick = () => {
          const t = b.dataset.t!;
          if (S.tags[t] > 0) S.tags[t] = -1;
          else delete S.tags[t];
          render();
        };
      });
    },
  });
  F.append(
    group(
      'Merkmale (Steam-Tags)',
      [tagBox, triChips(Object.fromEntries(popular.map((t) => [t, t])), () => S.tags, tc, true)],
      () => (S.tags = {}),
      'Grün = muss haben (alle), rot = ausschließen. Nur für Spiele, die es auch auf Steam gibt.',
    ),
    group('Technik', chipList(TECH, () => S.tech, (v) => (S.tech = v), countBy((g) => g.feat)), () => (S.tech = [])),
    group(
      'Sonstiges',
      [
        row('Altersfreigabe', selectEl([[0, 'egal'], [6, 'bis 6'], [12, 'bis 12'], [16, 'bis 16']], () => S.pegi, (v) => (S.pegi = +v))),
        row('Xbox-Bewertung', selectEl([[0, 'egal'], [3.5, 'ab 3,5 ★'], [4, 'ab 4 ★'], [4.5, 'ab 4,5 ★']], () => S.stars, (v) => (S.stars = +v))),
      ],
      () => {
        S.pegi = 0;
        S.stars = 0;
      },
    ),
  );
}

function syncControls() {
  controls.forEach((c) => c.sync());
  const search = $<HTMLInputElement>('#search');
  if (document.activeElement !== search) search.value = S.q;
  $<HTMLSelectElement>('#sort').value = S.sort;
}

// Aktive Filter als entfernbare Chips über der Liste
function renderActiveChips() {
  const items: [string, () => void][] = [];
  const r = (x: [number | null, number | null], fmt: (v: number) => string) =>
    x[0] !== null && x[1] !== null ? `${fmt(x[0])}–${fmt(x[1])}` : x[0] !== null ? `ab ${fmt(x[0])}` : `bis ${fmt(x[1]!)}`;
  S.plat.forEach((p) => items.push([PLATS[p], () => (S.plat = S.plat.filter((x) => x !== p))]));
  S.status.forEach((p) => items.push([STATUS[p], () => (S.status = S.status.filter((x) => x !== p))]));
  if (S.year.some((x) => x !== null)) items.push(['Jahr ' + r(S.year, String), () => (S.year = [null, null])]);
  if (S.mc.some((x) => x !== null)) items.push(['Metascore ' + r(S.mc, String), () => (S.mc = [null, null])]);
  if (S.us.some((x) => x !== null))
    items.push(['User Score ' + r(S.us, (v) => (v / 10).toFixed(1).replace('.', ',')), () => (S.us = [null, null])]);
  if (S.hours.some((x) => x !== null)) items.push([`${H_KINDS[S.hKind]} ${r(S.hours, String)} Std.`, () => (S.hours = [null, null])]);
  Object.entries(S.genres).forEach(([k, v]) => items.push([(v < 0 ? 'ohne ' : '') + (GENRES[k] || k), () => delete S.genres[k]]));
  S.modes.forEach((m) => items.push([MODES[m], () => (S.modes = S.modes.filter((x) => x !== m))]));
  if (S.online !== 'any') items.push([S.online === 'offline' ? 'offline spielbar' : 'reines Online-Spiel', () => (S.online = 'any')]);
  if (S.players) items.push([`mind. ${S.players} Spieler`, () => (S.players = 0)]);
  S.tier.forEach((t) => items.push([t, () => (S.tier = S.tier.filter((x) => x !== t))]));
  if (S.ow !== 'any') items.push([S.ow === 'yes' ? 'Open World' : 'keine Open World', () => (S.ow = 'any')]);
  Object.entries(S.tags).forEach(([k, v]) => items.push([(v < 0 ? 'ohne #' : '#') + k, () => delete S.tags[k]]));
  S.tech.forEach((m) => items.push([TECH[m], () => (S.tech = S.tech.filter((x) => x !== m))]));
  if (S.pegi) items.push([`Freigabe bis ${S.pegi}`, () => (S.pegi = 0)]);
  if (S.stars) items.push([`ab ${S.stars} ★`, () => (S.stars = 0)]);
  if (S.q) items.push([`„${S.q}“`, () => (S.q = '')]);

  const box = $('#activeChips');
  box.innerHTML = '';
  for (const [label, remove] of items) {
    const b = document.createElement('button');
    b.className = 'chip';
    b.textContent = label;
    b.onclick = () => {
      remove();
      render();
    };
    box.append(b);
  }
  if (items.length > 1) {
    const b = document.createElement('button');
    b.className = 'chip clear';
    b.textContent = 'Alle Filter löschen';
    b.onclick = () => {
      const { sort, tab } = S;
      S = defaults();
      S.sort = sort;
      S.tab = tab;
      render();
    };
    box.append(b);
  }
}

// ---------- Start ----------

async function init() {
  const res = await fetch(import.meta.env.BASE_URL + 'data/games.json', { cache: 'no-cache' });
  const data = (await res.json()) as { updated: string; games: Game[] };
  games = data.games;
  YEAR_MIN = Math.max(1980, Math.min(...games.map((g) => g.y || YEAR_MAX)));

  const sortSel = $<HTMLSelectElement>('#sort');
  sortSel.innerHTML = Object.entries(SORTS).map(([k, l]) => `<option value="${k}">${l}</option>`).join('');
  sortSel.onchange = () => {
    S.sort = sortSel.value;
    render();
  };
  let t = 0;
  $<HTMLInputElement>('#search').oninput = (e) => {
    clearTimeout(t);
    t = window.setTimeout(() => {
      S.q = (e.target as HTMLInputElement).value.trim();
      render();
    }, 150);
  };
  $('#toggleFilters').onclick = () => {
    if (matchMedia('(max-width: 800px)').matches) document.body.classList.toggle('filters-open');
    else document.body.classList.toggle('filters-hidden');
  };

  loadList();
  importFromUrl();
  loadUrl();
  buildFilters();
  document.querySelectorAll<HTMLButtonElement>('.tabs button').forEach((b) => {
    b.onclick = () => {
      S.tab = b.dataset.tab === 'list' ? 'list' : 'all';
      window.scrollTo(0, 0);
      render();
    };
  });
  $('#shareList').onclick = shareList;
  $('#grid').addEventListener('click', (e) => {
    const btn = (e.target as HTMLElement).closest<HTMLButtonElement>('button.add');
    if (btn) toggleList(btn.dataset.id!, btn);
  });
  render();

  const n = (f: (g: Game) => unknown) => games.filter(f).length;
  $('#footer').innerHTML = `Stand: ${new Date(data.updated).toLocaleString('de-DE', { dateStyle: 'medium', timeStyle: 'short' })} · ${games.length} Spiele (Deutschland).<br>
    Daten: Xbox-Game-Pass-Katalog &amp; Microsoft Store (Genre, Spielmodi, Freigabe), Metacritic (Metascore, User Score &amp; Original-Erscheinungsjahr, ${n((g) => g.mc !== undefined)} Spiele),
    <a href="https://howlongtobeat.com" target="_blank" rel="noopener">HowLongToBeat</a> (Spielzeit, ${n((g) => g.hMain !== undefined)} Spiele),
    Amazon Luna (Katalog Prime/Premium und Abholspiele), PlayStation Plus (Kataloge von playstation.com), Netflix (Liste von <a href="https://www.whats-on-netflix.com" target="_blank" rel="noopener">What's on Netflix</a>, geprüft auf netflix.com/de), Epic Games Store (Gratisspiele), Steam (Tags/Open World, ${n((g) => g.tags)} Spiele). Zuordnung automatisch über den Titel – Einzelne Fehler sind möglich.<br>
    „Meine Liste“ wird nur in diesem Browser gespeichert; mit „Liste übertragen“ nimmst du sie auf ein anderes Gerät mit.`;
}

init().catch((e) => {
  $('#grid').innerHTML = `<p class="empty">Daten konnten nicht geladen werden: ${esc(String(e))}</p>`;
});
