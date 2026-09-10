#!/usr/bin/env node
/**
 * 2048 自动验收脚本（不需要浏览器）
 * ==========================================================================
 * 作用：
 *   1) 用一个极简的“假 DOM + 假 localStorage”把 game/index.html 里的 <script> 跑起来；
 *   2) 对纯逻辑做单元测试（合并唯一性、计分、满盘判定、战绩只留 10 局、重置、主题持久化…）；
 *   3) 让 AI 在无人干预下整局自动对战，统计阶段二硬指标（合出 1024）的达成率。
 *
 * 用法：
 *   node game/tests/verify_game.mjs                     # 默认 10 局，标准档（固定 3 层）
 *   node game/tests/verify_game.mjs --games 40          # 复现 README 的 40 局表（标准档）
 *   node game/tests/verify_game.mjs --games 5 --level strong    # 强档（固定 4 层）
 *   node game/tests/verify_game.mjs --games 3 --level max --max-ms 3600000   # 极强档（自适应 ≤8 层）
 *
 * --level 直接复用 index.html 里 AI_LEVELS 的同一份预设（就是浏览器「AI 棋力」下拉框那几档），
 * 所以「界面上选的档」和「脚本跑的档」不可能对不上。显式传的 --max-depth / --time-ms /
 * --node-budget 优先级更高，可以单点调参。
 *
 * ⚠️ 跑强档以上时注意 --max-ms（单局时间上限，默认 180s）：慢档位单局可能要几十分钟，
 *    被掐断的局会在输出里标 [被 Ns 掐断]，并让脚本以失败退出 —— 拿半局成绩当结论没有意义。
 *
 * 退出码：全部通过 0；任一断言失败或达成率不达标 1。
 * ==========================================================================
 */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..', '..');
const HTML_PATH = path.join(ROOT, 'game', 'index.html');

/* ----------------------------- 命令行参数 ----------------------------- */
function argOf(name, fallback) {
  const i = process.argv.indexOf('--' + name);
  if (i === -1) return fallback;
  const v = process.argv[i + 1];
  return v === undefined || v.startsWith('--') ? true : v;
}
const GAMES = Number(argOf('games', 10));
const TIME_MS = Number(argOf('time-ms', 35));
const NODE_BUDGET = Number(argOf('node-budget', 220000));
const MAX_MS = Number(argOf('max-ms', 180000));
const QUICK = process.argv.includes('--quick');
const MAX_DEPTH = Number(argOf('max-depth', 3));
const MOVES = Number(argOf('moves', 20000));
const LEVEL_ID = argOf('level', null);
const hasFlag = (n) => process.argv.includes('--' + n);
const SEED_BASE = Number(argOf('seed', 20260910));
const MIN_PASS = Math.max(1, Math.ceil(GAMES * 0.8)); // 达成率门槛：≥80% 局数到达 1024

const DIM = '\x1b[2m', RED = '\x1b[31m', GREEN = '\x1b[32m', YELLOW = '\x1b[33m', BOLD = '\x1b[1m', OFF = '\x1b[0m';

/* ----------------------------- 测试记录器 ----------------------------- */
const results = { pass: 0, fail: 0, failures: [] };
function ok(name, extra = '') {
  results.pass++;
  console.log(`  ${GREEN}✓${OFF} ${name}${extra ? DIM + '  ' + extra + OFF : ''}`);
}
function bad(name, detail) {
  results.fail++;
  results.failures.push(`${name} → ${detail}`);
  console.log(`  ${RED}✗${OFF} ${name}  ${RED}${detail}${OFF}`);
}
function check(name, cond, detail = '') {
  if (cond) ok(name);
  else bad(name, detail || '断言失败');
}
function eq(name, actual, expected) {
  check(name, Object.is(actual, expected), `期望 ${JSON.stringify(expected)}，实际 ${JSON.stringify(actual)}`);
}
function section(title) {
  console.log(`\n${BOLD}${title}${OFF}`);
}

/* ==========================================================================
 * 极简 HTML ↔ JS 契约检查（不依赖任何第三方库）
 * ========================================================================== */
section('0. 单文件与 HTML↔JS 契约');

const html = fs.readFileSync(HTML_PATH, 'utf8');
const scripts = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)].map((m) => m[1]);

check('game/index.html 存在且非空', html.length > 5000, `${html.length} 字节`);
check('是单文件：只有内联 <script>，无 src 外链', !/<script\b[^>]*\bsrc=/i.test(html));
// 判定「不联网」之前必须先把注释剥掉：
//   HTML 注释 <!-- --> 、JS 块注释 /* */ 、JS 行注释 // 里出现参考链接是正常的
//   （比如 AI 段注释里写了参考实现的 GitHub 地址），那是给人看的文档，不是运行时会去请求的资源。
const htmlNoComments = html
  .replace(/<!--[\s\S]*?-->/g, '')
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/^[ \t]*\/\/.*$/gm, '');
check(
  '无外部样式表/网络请求',
  !/<link\b[^>]*rel=["']?stylesheet/i.test(html)
  && !/https?:\/\//i.test(htmlNoComments)
  && !/\b(fetch\s*\(|XMLHttpRequest|WebSocket|EventSource)\b/.test(htmlNoComments)
);
eq('恰好一个内联 <script>', scripts.length, 1);

const scriptSource = scripts[0] || '';
check(
  '逻辑层未使用 import / require / node API',
  !/\b(require|process\.|__dirname|import\s+[^("])\b/.test(scriptSource)
);

const idSet = new Set([...html.matchAll(/\bid=["']([^"']+)["']/g)].map((m) => m[1]));
const elIdsBlock = (scriptSource.match(/var EL_IDS\s*=\s*\{([\s\S]*?)\};/) || [, ''])[1];
const elIdsRefs = [...elIdsBlock.matchAll(/'([^']+)'/g)].map((m) => m[1]);
const refSet = new Set([
  ...[...scriptSource.matchAll(/getElementById\(\s*["']([^"']+)["']\s*\)/g)].map((m) => m[1]),
  ...[...scriptSource.matchAll(/querySelector\(\s*["']#([^"']+)["']\s*\)/g)].map((m) => m[1]),
  ...elIdsRefs
]);
const missingIds = [...refSet].filter((id) => !idSet.has(id));
check(
  `JS 引用的所有元素 id 都存在于 HTML（共 ${refSet.size} 个）`,
  refSet.size >= 28 && missingIds.length === 0,
  `缺失：${missingIds.join(', ') || '无'}`
);

/* ==========================================================================
 * 假 DOM / 假 localStorage：让真实的 index.html 脚本在 Node 里跑起来
 * ========================================================================== */
function makeStorageStub() {
  const map = new Map();
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => { map.set(k, String(v)); },
    removeItem: (k) => { map.delete(k); },
    clear: () => map.clear(),
    _map: map
  };
}

function makeDom() {
  const elements = new Map();
  const listeners = { window: {}, element: {} };

  function makeElement(tag = 'div', id = '') {
    const node = {
      tagName: String(tag).toUpperCase(),
      id,
      style: {
        _p: {},
        setProperty(k, v) { this._p[k] = v; },
        getPropertyValue(k) { return this._p[k]; }
      },
      dataset: {},
      children: [],
      textContent: '',
      value: '10',
      disabled: false,
      className: '',
      classList: {
        _s: new Set(),
        add(...c) { c.forEach((x) => this._s.add(x)); },
        remove(...c) { c.forEach((x) => this._s.delete(x)); },
        contains(c) { return this._s.has(c); },
        toggle(c) { this._s.has(c) ? this._s.delete(c) : this._s.add(c); }
      },
      getBoundingClientRect() {
        const wide = id === 'board' ? 480 : 0;
        return { width: wide, height: wide, top: 0, left: 0, right: wide, bottom: wide, x: 0, y: 0 };
      },
      appendChild(child) { this.children.push(child); return child; },
      append(...kids) { kids.forEach((k) => this.children.push(k)); },
      replaceChildren(...kids) {
        this.children = kids.length === 1 && kids[0] && kids[0].__fragment
          ? kids[0].children.slice()
          : kids.slice();
      },
      setAttribute(k, v) { this.dataset['attr_' + k] = v; },
      getAttribute(k) { return this.dataset['attr_' + k] ?? null; },
      addEventListener(type, fn) {
        (listeners.element[id] ||= {})[type] ||= [];
        listeners.element[id][type].push(fn);
      },
      removeEventListener() {},
      focus() {},
      click() { (listeners.element[id]?.click || []).forEach((fn) => fn({ preventDefault() {} })); },
      querySelector() { return null; },
      querySelectorAll() { return []; }
    };
    // className 与 classList 保持同步
    Object.defineProperty(node, 'className', {
      get() { return [...node.classList._s].join(' '); },
      set(v) { node.classList._s = new Set(String(v).split(/\s+/).filter(Boolean)); }
    });
    return node;
  }

  function getById(id) {
    if (!elements.has(id)) elements.set(id, makeElement('div', id));
    return elements.get(id);
  }

  const htmlEl = makeElement('html', '__html');
  htmlEl.dataset.attr_theme = 'dark';

  const document = {
    documentElement: htmlEl,
    body: makeElement('body', '__body'),
    getElementById: getById,
    createElement: (tag) => makeElement(tag),
    createDocumentFragment: () => {
      const frag = makeElement('#fragment');
      frag.__fragment = true;
      return frag;
    },
    addEventListener: () => {},
    querySelector: () => null,
    querySelectorAll: () => []
  };

  const localStorage = makeStorageStub();
  const context = {
    console,
    Date,
    Math,
    JSON,
    Number,
    String,
    Object,
    Array,
    Boolean,
    Error,
    isNaN,
    parseInt,
    parseFloat,
    Float64Array,
    URLSearchParams,
    setTimeout: () => 0,
    clearTimeout: () => {},
    setInterval: () => 0,
    clearInterval: () => {},
    requestAnimationFrame: () => 0,
    document,
    localStorage
  };
  const win = {
    document,
    localStorage,
    console,
    URLSearchParams,
    location: { search: '' },
    matchMedia: () => ({ matches: true, addEventListener() {}, addListener() {} }),
    addEventListener(type, fn) {
      (listeners.window[type] ||= []).push(fn);
    },
    removeEventListener() {},
    setTimeout: () => 0,
    clearTimeout: () => {},
    requestAnimationFrame: () => 0
  };
  context.window = win;
  context.globalThis = context;
  win.window = win;
  win.__2048__ = undefined;

  return {
    document,
    window: win,
    localStorage,
    context,
    getById,
    elements,
    fireWindow(type, ev) { (listeners.window[type] || []).forEach((fn) => fn(ev)); },
    fireElement(id, type, ev) { (listeners.element[id]?.[type] || []).forEach((fn) => fn(ev)); }
  };
}

const dom = makeDom();
const sandbox = vm.createContext(dom.context);
vm.runInContext(scriptSource, sandbox, { filename: 'game/index.html#inline-script' });

const G = dom.window.Game2048;
const UI = dom.window.__2048__;

section('1. 游戏脚本可加载');
check('纯逻辑层 window.Game2048 已导出', !!G);
check('UI 桥接层 window.__2048__ 已导出', !!UI);
if (!G || !UI) {
  console.error(`\n${RED}脚本未能初始化，后续测试无法进行。${OFF}`);
  process.exit(1);
}

/* ==========================================================================
 * 2. 纯逻辑单元测试
 * ========================================================================== */
section('2. 核心规则（纯逻辑）');

// 合并唯一性：一行只有 4 格，[2,2,2,2] 只能合成 [4,4]，不能一步变 8
eq('slideRow([2,2,2,2]) → [4,4,0,0]', JSON.stringify(G.slideRow([2, 2, 2, 2]).row), JSON.stringify([4, 4, 0, 0]));
eq('slideRow([2,2,2,2]) 得分 +8', G.slideRow([2, 2, 2, 2]).gained, 8);
eq('slideRow([4,4,8,8]) → [8,16,0,0]', JSON.stringify(G.slideRow([4, 4, 8, 8]).row), JSON.stringify([8, 16, 0, 0]));
eq('slideRow([2,0,0,2]) → [4,0,0,0]', JSON.stringify(G.slideRow([2, 0, 0, 2]).row), JSON.stringify([4, 0, 0, 0]));
eq('slideRow([0,0,0,2]) → [2,0,0,0]', JSON.stringify(G.slideRow([0, 0, 0, 2]).row), JSON.stringify([2, 0, 0, 0]));
eq('slideRow 不对 3 个相同值越级合并', JSON.stringify(G.slideRow([2, 2, 2, 0]).row), JSON.stringify([4, 2, 0, 0]));

// 位棋盘（AI 搜索用的整数表示）必须和数组层规则完全一致。
// 这里用 G.slideRow（已被单元测试验证过）当参考实现，逐方向比对，能抓出位运算里的错。
{
  const refMove = (grid, dir) => {
    const out = new Array(16).fill(0);
    const pick = (i, j) => (dir === 'left' ? i * 4 + j
      : dir === 'right' ? i * 4 + (3 - j)
        : dir === 'up' ? j * 4 + i
          : (3 - j) * 4 + i);
    for (let i = 0; i < 4; i++) {
      const line = [];
      for (let j = 0; j < 4; j++) line.push(grid[pick(i, j)]);
      const r = G.slideRow(line);
      for (let j = 0; j < 4; j++) out[pick(i, j)] = r.row[j];
    }
    return out;
  };

  const grid = G.createGrid();
  const rnd = G.makeRng(24680);
  let checked = 0, diffArr = 0, diffBit = 0;
  for (let step = 0; step < 2500; step++) {
    G.addRandomTile(grid, rnd);
    const p = G.packGridLoHi(grid);
    const cands = G.allMovesLoHi(p.lo, p.hi);
    for (const dir of ['left', 'right', 'up', 'down']) {
      const ref = refMove(grid, dir);
      const arr = G.applyMove(grid.slice(), dir);
      const bit = cands.find((c) => c.dir === dir);
      checked++;
      if (JSON.stringify(ref) !== JSON.stringify(arr.grid)) diffArr++;
      const bitGrid = bit ? G.unpackLoHi(bit.lo, bit.hi) : grid;
      if (JSON.stringify(bitGrid) !== JSON.stringify(ref)) diffBit++;
    }
    if (!G.canMove(grid)) {
      const blank = G.createGrid();
      for (let i = 0; i < 16; i++) grid[i] = blank[i];
    }
  }
  check(`数组层移动与参考实现一致（${checked} 次方向对比）`, diffArr === 0, `${diffArr} 处不一致`);
  check(`位棋盘移动与参考实现一致（${checked} 次方向对比）`, diffBit === 0, `${diffBit} 处不一致`);
}

// 角块启发式：大块放角上分高，把最大块挪走分应下降
{
  const corner = G.createGrid();
  corner[0] = 1024;
  corner[1] = 512;
  corner[4] = 256;
  const pc = G.packGridLoHi(corner);
  const scoreCorner = G.cornerHeuristic(pc.lo, pc.hi);

  const scattered = G.createGrid();
  scattered[5] = 1024;
  scattered[10] = 512;
  scattered[15] = 256;
  const ps = G.packGridLoHi(scattered);
  const scoreScattered = G.cornerHeuristic(ps.lo, ps.hi);
  check('角块启发式：大块堆在角上比散在中间分高', scoreCorner > scoreScattered, `${scoreCorner} vs ${scoreScattered}`);

  const oneCorner = G.createGrid();
  oneCorner[0] = 2;
  const p1 = G.packGridLoHi(oneCorner);
  eq('角块启发式：左上角放 2 = 10×2', G.cornerHeuristic(p1.lo, p1.hi), 20);
  const br = G.createGrid();
  br[15] = 2;
  const p2 = G.packGridLoHi(br);
  eq('角块启发式：右下角放 2 同样 = 20（四个角都算）', G.cornerHeuristic(p2.lo, p2.hi), 20);
}

// 自适应深度：棋盘越满，搜得越深
{
  const empty = G.createGrid();
  const pe = G.packGridLoHi(empty);
  const dEmpty = G.aiPickDepth(pe.lo, pe.hi);
  const busy = G.createGrid();
  const vals = [2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2, 4, 8, 16, 32, 64];
  for (let i = 0; i < 16; i++) busy[i] = vals[i];
  const pb = G.packGridLoHi(busy);
  const dBusy = G.aiPickDepth(pb.lo, pb.hi);
  check('自适应深度：空棋盘用浅搜', dEmpty === 2, `depth=${dEmpty}`);
  check('自适应深度：复杂局面搜得更深', dBusy > dEmpty, `空=${dEmpty}, 满=${dBusy}`);
  check('自适应深度不超过上限', dBusy <= G.AI_MAX_DEPTH, `depth=${dBusy}`);
}

/* 棋力档位：必须真的是「档位越高搜得越深」，而不是只在界面上换个名字。
 * 做法：同样 260 步、不同种子跑闪电档和标准档，比较平均搜索深度。 */
{
  const ids = G.AI_LEVELS.map((l) => l.id);
  check('棋力档位：至少 3 档', G.AI_LEVELS.length >= 3, `${G.AI_LEVELS.length} 档：${ids.join(' / ')}`);
  check('棋力档位：id 唯一', new Set(ids).size === ids.length, ids.join(','));
  check(
    '棋力档位：每档都配齐 depth / timeMs / nodesPerDir / 说明',
    G.AI_LEVELS.every((l) => typeof l.name === 'string' && l.name
      && Number.isFinite(l.depth) && Number.isFinite(l.timeMs)
      && Number.isFinite(l.nodesPerDir) && typeof l.note === 'string' && l.note),
    ''
  );
  check('棋力档位：档位越高深度上限越大（不会出现高档反而更浅）',
    G.AI_LEVELS.every((l, i) => i === 0 || l.depth === 0 || G.AI_LEVELS[i - 1].depth === 0 || l.depth >= G.AI_LEVELS[i - 1].depth),
    G.AI_LEVELS.map((l) => `${l.name}=${l.depth}`).join(' ')
  );
  let threw = false;
  try { G.playGame({ level: 'not-a-level', maxMoves: 1 }); } catch (e) { threw = true; }
  check('棋力档位：传入不存在的档位会直接报错（而不是悄悄退回默认档）', threw);

  // 行为断言：同一批种子、同样步数，标准档的平均搜索深度必须高于闪电档
  const probe = (level) => {
    const runs = [1, 2, 3].map((i) => G.playGame({
      rand: G.makeRng(900000 + i * 7919), level, maxMoves: 260, maxMs: 60000
    }));
    return runs.reduce((a, r) => a + r.avgDepth, 0) / runs.length;
  };
  const dFlash = probe('flash');
  const dNormal = probe('normal');
  check(
    '棋力档位：标准档比闪电档搜得更深（档位真的接到了搜索上）',
    dNormal > dFlash,
    `闪电 ${dFlash.toFixed(2)} 层 < 标准 ${dNormal.toFixed(2)} 层`
  );
}

// 四个方向
const gridA = [
  2, 2, 4, 0,
  0, 0, 0, 0,
  8, 0, 8, 8,
  0, 4, 0, 4
];
const leftA = G.applyMove(gridA, 'left');
eq('向左：有方块移动', leftA.moved, true);
eq('向左：本步得分 = 4+16+8 = 28', leftA.gained, 28);
eq('向左：第一行合并结果', JSON.stringify([leftA.grid[0], leftA.grid[1], leftA.grid[2], leftA.grid[3]]), JSON.stringify([4, 4, 0, 0]));
eq('向左：第三行 8,0,8,8 → 16,8', JSON.stringify([leftA.grid[8], leftA.grid[9], leftA.grid[10], leftA.grid[11]]), JSON.stringify([16, 8, 0, 0]));
eq('向左：第四行 0,4,0,4 → 8', JSON.stringify([leftA.grid[12], leftA.grid[13], leftA.grid[14], leftA.grid[15]]), JSON.stringify([8, 0, 0, 0]));

const rightA = G.applyMove(gridA, 'right');
eq('向右：第四行 0,4,0,4 → 末尾 8', rightA.grid[15], 8);
const upA = G.applyMove(gridA, 'up');
eq('向上：第一列 2,.,8,. → 2,8', JSON.stringify([upA.grid[0], upA.grid[4], upA.grid[8], upA.grid[12]]), JSON.stringify([2, 8, 0, 0]));
const downA = G.applyMove(gridA, 'down');
// 向下：先读到的是最下面那一格
eq('向下：第三列 4,·,8,4 → 底部 4,8,4', JSON.stringify([downA.grid[2], downA.grid[6], downA.grid[10], downA.grid[14]]), JSON.stringify([0, 0, 4, 8]));

// 无效移动必须返回 moved=false（否则会凭空冒出新方块）
const full = [2, 4, 2, 4, 4, 2, 4, 2, 2, 4, 2, 4, 4, 2, 4, 2];
eq('无路可走时 canMove = false', G.canMove(full), false);
const stuck = G.applyMove(full, 'left');
eq('无效移动 moved = false', stuck.moved, false);
const almostFull = full.slice();
almostFull[0] = 0;
eq('有空格时 canMove = true', G.canMove(almostFull), true);
eq('满盘但存在相邻同值时可继续', G.canMove([2, 2, 4, 8, 4, 8, 16, 32, 8, 16, 32, 64, 16, 32, 64, 128]), true);

// 新方块只落在空格
const g2 = G.createGrid();
g2[5] = 2;
const rng = G.makeRng(7);
let spawnOnEmpty = true;
for (let i = 0; i < 300; i++) {
  const pos = G.addRandomTile(g2, rng);
  if (pos === 5) spawnOnEmpty = false;
  if (pos === -1) break;
  if (g2[pos] !== 2 && g2[pos] !== 4) spawnOnEmpty = false;
  g2[pos] = 0;
}
check('新方块只落在空格，且取值只能是 2 或 4', spawnOnEmpty);

// 可复现随机：同种子产生同样的序列（测试结果能复现的前提）
{
  const r1 = G.makeRng(42), r2 = G.makeRng(42), r3 = G.makeRng(43);
  const s1 = [r1(), r1(), r1()].map((v) => Number(v.toFixed(8)));
  const s2 = [r2(), r2(), r2()].map((v) => Number(v.toFixed(8)));
  const s3 = [r3(), r3(), r3()].map((v) => Number(v.toFixed(8)));
  eq('同种子随机序列可复现', JSON.stringify(s1), JSON.stringify(s2));
  check('不同种子序列不同', JSON.stringify(s1) !== JSON.stringify(s3));
}

/* ==========================================================================
 * 3. 阶段一：界面状态 / 计分制 / 重置 / 主题 / 战绩
 * ========================================================================== */
section('3. 阶段一验收（界面与新增功能）');

UI.newGame();
check('新局棋盘恰好 16 个格子', G.CELLS === 16);
eq('新局有 2 个初始方块', UI.state.grid.filter((v) => v !== 0).length, 2);
eq('新局得分清零', UI.state.score, 0);
eq('新局步数清零', UI.state.moves, 0);
eq('新局界面上渲染出 16 个背景格', dom.getById('grid-bg').children.length, 16);
eq('新局界面上的分数显示同步', dom.getById('score').textContent, '0');

// 连续移动 40 步：只统计「有效的左移」，比对内部计分与规则层计分是否一致
let expectedScore = 0, movedCount = 0, mergesSeen = 0, spawnAlwaysOnEmpty = true;
for (let i = 0; i < 400 && movedCount < 40; i++) {
  const probe = G.applyMove(UI.state.grid, 'left');
  if (!probe.moved) {
    const right = G.applyMove(UI.state.grid, 'right');
    if (!right.moved) break;
    UI.doMove('right');
    expectedScore += right.gained;
    mergesSeen += right.merges.length;
    movedCount++;
    continue;
  }
  const before = UI.state.grid.filter((v) => v !== 0).length;
  const beforeEmpty = 16 - before;
  UI.doMove('left');
  expectedScore += probe.gained;
  mergesSeen += probe.merges.length;
  movedCount++;
  const after = UI.state.grid.filter((v) => v !== 0).length;
  if (after > Math.min(16, before + 1)) spawnAlwaysOnEmpty = false;
  if (16 - after < 0) spawnAlwaysOnEmpty = false;
  void beforeEmpty;
}
check(`连续 ${movedCount} 步移动后界面得分 === 规则层累加分`, UI.state.score === expectedScore, `界面 ${UI.state.score} vs 期望 ${expectedScore}`);
check('每次移动最多新增 1 个方块', spawnAlwaysOnEmpty);
eq('界面分数元素与内部状态一致', dom.getById('score').textContent, String(UI.state.score));
eq('步数统计正确', UI.state.moves, movedCount);
check('确实发生过合并', mergesSeen > 0, `合并 ${mergesSeen} 次`);
check('得分随之增长', UI.state.score > 0, `得分 ${UI.state.score}`);

// 最高分持久化
const bestNow = Number(dom.getById('best').textContent);
check('最高分已记录且 ≥ 当前得分', bestNow >= UI.state.score, `best=${bestNow}, score=${UI.state.score}`);
const persisted = JSON.parse(dom.localStorage.getItem(UI.keys.state) || '{}');
eq('最高分写入 localStorage', persisted.best, bestNow);

// 主题切换 + 刷新保留
const themeBefore = dom.document.documentElement.getAttribute('data-theme');
dom.getById('btn-theme').click();
const themeAfter = dom.document.documentElement.getAttribute('data-theme');
check('一键切换主题即时生效', themeBefore !== themeAfter, `${themeBefore} → ${themeAfter}`);
eq('主题写入 localStorage（刷新后保留）', dom.localStorage.getItem(UI.keys.theme), themeAfter);
eq('主题落在 data-theme 属性上（CSS 变量驱动）', dom.document.documentElement.getAttribute('data-theme'), themeAfter);

// 多局战绩：每次真实结算都追加一条，并且最多只保留最近 10 局
UI.setRecords([]);
UI.setStats({ best: 0, games: 0 });
for (let i = 0; i < 12; i++) {
  UI.newGame();
  UI.state.score = (i + 1) * 10;      // 造 12 局结算，检验裁剪逻辑
  UI.state.moves = i + 1;
  UI.finishGame();
}
const recs = UI.getRecords();
eq('连开 12 局后只保留最近 10 局', recs.length, 10);
eq('保留的是最近的记录（第一条是第 3 局）', recs[0].score, 30);
eq('最新一局在列表末尾', recs[9].score, 120);
check('战绩列表 DOM 渲染出 10 条', dom.getById('records').children.length === 10, `${dom.getById('records').children.length} 条`);
const recStorage = JSON.parse(dom.localStorage.getItem(UI.keys.records) || '[]');
eq('战绩写入 localStorage', recStorage.length, 10);

// 重置按钮：清空最高分 / 局数 / 战绩
dom.getById('btn-reset').click();
eq('重置后最高分归零', Number(dom.getById('best').textContent), 0);
eq('重置后局数归零', Number(dom.getById('st-games').textContent), 0);
eq('重置后战绩清空', UI.getRecords().length, 0);
eq('重置后 localStorage 中的最高分记录归零', JSON.parse(dom.localStorage.getItem(UI.keys.state) || '{}').best, 0);
eq('重置后战绩区显示空状态占位', dom.getById('records').children.length, 1);

// 键盘输入
const moveBefore = UI.state.moves;
dom.fireWindow('keydown', { key: 'ArrowLeft', preventDefault() {} });
dom.fireWindow('keydown', { key: 'a', preventDefault() {} });
check('键盘 ↑↓←→ / WASD 能操作（或该方向无效）', UI.state.moves >= moveBefore, `步数 ${moveBefore} → ${UI.state.moves}`);

// 拖拽/滑动
const movesBeforeDrag = UI.state.moves;
dom.fireElement('board', 'pointerdown', { clientX: 200, clientY: 200 });
dom.fireWindow('pointerup', { clientX: 300, clientY: 200 });
check('鼠标拖拽可操作棋盘', UI.state.moves >= movesBeforeDrag, `步数 ${movesBeforeDrag} → ${UI.state.moves}`);

/* ==========================================================================
 * 4. 阶段二：AI 无人干预自动对战，硬指标 = 合出 1024
 * ========================================================================== */
section('4. 阶段二硬指标（AI 自动操作，全程无人工）');

const perGame = [];
const t0 = Date.now();

/* 棋力档位：直接复用 index.html 里 AI_LEVELS 的同一份预设（就是浏览器下拉框里的那几档），
 * 这样「界面上选的档」和「验收脚本跑的档」不可能对不上。
 * 显式传了的 --max-depth / --time-ms / --node-budget 优先级更高，方便单点调参。 */
const LEVEL = LEVEL_ID && LEVEL_ID !== true ? G.levelById(String(LEVEL_ID)) : null;
if (LEVEL_ID && !LEVEL) {
  console.log(`\n${RED}未知的档位：${LEVEL_ID}${OFF}  可选：${G.AI_LEVELS.map((l) => l.id).join(' / ')}\n`);
  process.exit(2);
}
const aiOptions = LEVEL
  ? {
    level: LEVEL.id,
    maxDepth: hasFlag('max-depth') ? MAX_DEPTH : LEVEL.depth,
    timeMs: hasFlag('time-ms') ? TIME_MS : LEVEL.timeMs,
    nodesPerDir: hasFlag('node-budget') ? NODE_BUDGET : LEVEL.nodesPerDir
  }
  : {
    depth: 0,                 // 走 aiStep 同一条路径：自适应深度 + 上限
    maxDepth: MAX_DEPTH,
    timeMs: TIME_MS,
    /* ⚠️ 这里的默认值必须是 G.AI_NODES_PER_DIR（400000），不能是 --node-budget 的默认 220000：
     *    换掉它就会改变 README 那张 40 局表的结果。要覆盖请**显式**传 --node-budget。 */
    nodesPerDir: hasFlag('node-budget') ? NODE_BUDGET : G.AI_NODES_PER_DIR
  };
const cfgLabel = LEVEL
  ? `档位 ${LEVEL.name}（depth=${LEVEL.depth || '自适应'}，timeMs=${aiOptions.timeMs}，nodes/dir=${aiOptions.nodesPerDir}）`
  : `自定义（maxDepth=${MAX_DEPTH}，timeMs=${TIME_MS}，nodes/dir=${aiOptions.nodesPerDir}）`;
console.log(`  ${DIM}配置：${cfgLabel}，单局上限 ${MAX_MS / 1000}s / ${MOVES} 步${OFF}`);

for (let i = 0; i < GAMES; i++) {
  const seed = SEED_BASE + i * 104729;
  const res = G.playGame({
    rand: G.makeRng(seed),
    ...aiOptions,
    maxMs: MAX_MS,
    continueAfterWin: true,
    maxMoves: MOVES
  });
  perGame.push({ seed, ...res });
  const tag = res.reached1024 ? `${GREEN}达标${OFF}` : `${RED}未达标${OFF}`;
  const bonus = res.reached2048 ? ` ${YELLOW}(2048!)${OFF}` : '';
  // ⚠️ 没下完的局必须显式标出来：它的最大方块只是「跑到一半的成绩」
  const cut = res.truncatedBy === 'ms' ? ` ${YELLOW}[被 ${MAX_MS / 1000}s 掐断]${OFF}`
    : res.truncatedBy === 'moves' ? ` ${DIM}[只跑了 ${MOVES} 步]${OFF}` : '';
  console.log(
    `  第 ${String(i + 1).padStart(2)} 局  种子=${seed}  得分=${String(res.score).padStart(6)}` +
    `  最大块=${String(res.maxTile).padStart(4)}  步数=${String(res.moves).padStart(4)}` +
    `  用时=${String((res.elapsedMs / 1000).toFixed(1)).padStart(6)}s  平均决策=${res.avgStepMs.toFixed(1)}ms` +
    `  平均深度=${res.avgDepth.toFixed(1)}  ${tag}${bonus}${cut}`
  );
}
const totalMs = Date.now() - t0;

const reached1024 = perGame.filter((g) => g.reached1024).length;
const reached2048 = perGame.filter((g) => g.reached2048).length;
const reached4096 = perGame.filter((g) => g.reached4096).length;
const reached8192 = perGame.filter((g) => g.reached8192).length;
const cutByMs = perGame.filter((g) => g.truncatedBy === 'ms').length;
const cutByMoves = perGame.filter((g) => g.truncatedBy === 'moves').length;
const avgScore = Math.round(perGame.reduce((a, g) => a + g.score, 0) / perGame.length);
const maxTileOverall = Math.max(...perGame.map((g) => g.maxTile));
const avgMoves = Math.round(perGame.reduce((a, g) => a + g.moves, 0) / perGame.length);
const avgStep = perGame.reduce((a, g) => a + g.avgStepMs, 0) / perGame.length;
const avgDepth = perGame.reduce((a, g) => a + g.avgDepth, 0) / perGame.length;

console.log('');
check(
  `AI 合出 1024 的局数 ≥ ${MIN_PASS}/${GAMES}（${(reached1024 / GAMES * 100).toFixed(0)}%）`,
  reached1024 >= MIN_PASS,
  `实际 ${reached1024}/${GAMES} 局达标`
);
check('整局无人干预（AI 自己选方向、自己结束）', perGame.every((g) => g.moves > 0 && g.over !== undefined));
check(`所有局都超过 200 步（说明是完整对局而非提前卡死）`, perGame.every((g) => g.moves >= 200), `最少 ${Math.min(...perGame.map((g) => g.moves))} 步`);
/* 「单步耗时 < 120ms」只对**默认档及更轻的档**成立（那是「浏览器不卡」的要求）。
 * 强/极强档是故意用时间换棋力的，跑它们时这条不该再当门槛，只提示。 */
const lightEnough = !LEVEL || (LEVEL.depth > 0 && LEVEL.depth <= 3);
if (lightEnough) {
  check('单次决策平均耗时 < 120ms（浏览器不会卡）', avgStep < 120, `平均 ${avgStep.toFixed(1)}ms`);
} else {
  console.log(`  ${DIM}· 单次决策平均耗时 ${avgStep.toFixed(1)}ms（${LEVEL.name}档是「用时间换棋力」，不做 <120ms 要求）${OFF}`);
}

console.log(`\n${BOLD}汇总${OFF}`);
console.log(`  配置                 ${LEVEL ? LEVEL.name + ' 档' : '自定义'}（节点/方向 ${aiOptions.nodesPerDir}，单步预算 ${aiOptions.timeMs}ms）`);
console.log(`  局数                  ${GAMES}`);
console.log(`  合出 1024            ${reached1024}/${GAMES}  ${reached1024 >= MIN_PASS ? GREEN + '达标' : RED + '未达标'}${OFF}`);
console.log(`  合出 2048（加分项）  ${reached2048}/${GAMES}`);
console.log(`  合出 4096            ${reached4096}/${GAMES}`);
console.log(`  合出 8192            ${reached8192}/${GAMES}`);
console.log(`  平均得分             ${avgScore}`);
console.log(`  最高方块             ${maxTileOverall}`);
console.log(`  平均步数             ${avgMoves}`);
console.log(`  平均搜索深度          ${avgDepth.toFixed(2)} 层`);
console.log(`  平均单步决策耗时      ${avgStep.toFixed(1)} ms`);
console.log(`  全部局总耗时          ${(totalMs / 1000).toFixed(1)} s`);
if (cutByMoves) {
  console.log(`  ${DIM}· ${cutByMoves}/${GAMES} 局是跑到 --moves ${MOVES} 就停的（跑短程 A/B 用的模式，不算真实成绩）${OFF}`);
}
if (cutByMs) {
  console.log(`  ${YELLOW}⚠️ 有 ${cutByMs}/${GAMES} 局被单局时间上限（${MAX_MS / 1000}s）掐断，不是真的下完 —— 这些局的数据不能当最终成绩${OFF}`);
}

/* ⚠️ 被**时间**掐断的局不能当成绩：拿半局结果当结论是自欺欺人。
 *    被 --moves 掐断则是刻意的短程基准，放行但要显式提示。 */
check('没有一局是被单局时间上限掐断的', cutByMs === 0,
  `${cutByMs} 局没下完就被 MAX_MS=${MAX_MS}ms 掐断了；跑慢档位请加大 --max-ms`);

// 生成可直接粘贴进 README 的 Markdown 表格
if (process.argv.includes('--markdown')) {
  const lines = [
    '| 局 | 随机种子 | 得分 | 最大方块 | 步数 | 是否达成 1024 | 是否达成 2048 | 用时(s) |',
    '| ---: | ---: | ---: | ---: | ---: | :---: | :---: | ---: |',
    ...perGame.map((g, i) =>
      `| ${i + 1} | ${g.seed} | ${g.score} | ${g.maxTile} | ${g.moves} | ${g.reached1024 ? '✅' : '❌'} | ${g.reached2048 ? '✅' : '—'} | ${(g.elapsedMs / 1000).toFixed(1)} |`)
  ];
  console.log('\n' + lines.join('\n'));
}

/* ==========================================================================
 * 结果汇总
 * ========================================================================== */
section('结果');
console.log(`  断言通过 ${GREEN}${results.pass}${OFF} 项，失败 ${results.fail ? RED : ''}${results.fail}${OFF} 项`);
if (results.failures.length) {
  console.log(`\n${RED}失败明细：${OFF}`);
  results.failures.forEach((f) => console.log('  - ' + f));
}
const passAll = results.fail === 0 && reached1024 >= MIN_PASS;
console.log(`\n${passAll ? GREEN + BOLD + '验收通过' : RED + BOLD + '验收未通过'}${OFF}\n`);
process.exit(passAll ? 0 : 1);
