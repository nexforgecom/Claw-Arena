// Star Office UI - 游戏主逻辑
// 依赖: layout.js（必须在这个之前加载）

// 检测浏览器是否支持 WebP
let supportsWebP = false;

// 方法 1: 使用 canvas 检测
function checkWebPSupport() {
  return new Promise((resolve) => {
    const canvas = document.createElement('canvas');
    if (canvas.getContext && canvas.getContext('2d')) {
      resolve(canvas.toDataURL('image/webp').indexOf('data:image/webp') === 0);
    } else {
      resolve(false);
    }
  });
}

// 方法 2: 使用 image 检测（备用）
function checkWebPSupportFallback() {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve(true);
    img.onerror = () => resolve(false);
    img.src = 'data:image/webp;base64,UklGRkoAAABXRUJQVlA4WAoAAAAQAAAAAAAAAAAAQUxQSAwAAAABBxAR/Q9ERP8DAABWUDggGAAAADABAJ0BKgEAAQADADQlpAADcAD++/1QAA==';
  });
}

// 获取文件扩展名（根据 WebP 支持情况 + 布局配置的 forcePng）
function getExt(pngFile) {
  // star-working-spritesheet.png 太宽了，WebP 不支持，始终用 PNG
  if (pngFile === 'star-working-spritesheet.png') {
    return '.png';
  }
  // 如果布局配置里强制用 PNG，就用 .png
  if (LAYOUT.forcePng && LAYOUT.forcePng[pngFile.replace(/\.(png|webp)$/, '')]) {
    return '.png';
  }
  return supportsWebP ? '.webp' : '.png';
}

const config = {
  type: Phaser.AUTO,
  width: LAYOUT.game.width,
  height: LAYOUT.game.height,
  parent: 'game-container',
  pixelArt: true,
  physics: { default: 'arcade', arcade: { gravity: { y: 0 }, debug: false } },
  scene: { preload: preload, create: create, update: update }
};

let totalAssets = 0;
let loadedAssets = 0;
let loadingProgressBar, loadingProgressContainer, loadingOverlay, loadingText;

// Memo 相关函数
async function loadMemo() {
  const memoDate = document.getElementById('memo-date');
  const memoContent = document.getElementById('memo-content');

  try {
    const response = await fetch('/yesterday-memo?t=' + Date.now(), { cache: 'no-store' });
    const data = await response.json();

    if (data.success && data.memo) {
      memoDate.textContent = data.date || '';
      memoContent.innerHTML = data.memo.replace(/\n/g, '<br>');
    } else {
      memoContent.innerHTML = '<div id="memo-placeholder">暂无昨日日记</div>';
    }
  } catch (e) {
    console.error('加载 memo 失败:', e);
    memoContent.innerHTML = '<div id="memo-placeholder">加载失败</div>';
  }
}

// 更新加载进度
function updateLoadingProgress() {
  loadedAssets++;
  const percent = Math.min(100, Math.round((loadedAssets / totalAssets) * 100));
  if (loadingProgressBar) {
    loadingProgressBar.style.width = percent + '%';
  }
  if (loadingText) {
    loadingText.textContent = `正在加载 Star 的像素办公室... ${percent}%`;
  }
}

// 隐藏加载界面
function hideLoadingOverlay() {
  setTimeout(() => {
    if (loadingOverlay) {
      loadingOverlay.style.transition = 'opacity 0.5s ease';
      loadingOverlay.style.opacity = '0';
      setTimeout(() => {
        loadingOverlay.style.display = 'none';
      }, 500);
    }
  }, 300);
}

const STATES = {
  idle: { name: '待命', area: 'breakroom' },
  writing: { name: '整理文档', area: 'writing' },
  researching: { name: '搜索信息', area: 'researching' },
  executing: { name: '执行任务', area: 'writing' },
  syncing: { name: '同步备份', area: 'writing' },
  error: { name: '出错了', area: 'error' }
};

const BUBBLE_TEXTS = {
  idle: [
    '待命中：耳朵竖起来了',
    '我在这儿，随时可以开工',
    '先把桌面收拾干净再说',
    '呼——给大脑放个风',
    '今天也要优雅地高效',
    '等待，是为了更准确的一击',
    '咖啡还热，灵感也还在',
    '我在后台给你加 Buff',
    '状态：静心 / 充电',
    '小猫说：慢一点也没关系'
  ],
  writing: [
    '进入专注模式：勿扰',
    '先把关键路径跑通',
    '我来把复杂变简单',
    '把 bug 关进笼子里',
    '写到一半，先保存',
    '把每一步都做成可回滚',
    '今天的进度，明天的底气',
    '先收敛，再发散',
    '让系统变得更可解释',
    '稳住，我们能赢'
  ],
  researching: [
    '我在挖证据链',
    '让我把信息熬成结论',
    '找到了：关键在这里',
    '先把变量控制住',
    '我在查：它为什么会这样',
    '把直觉写成验证',
    '先定位，再优化',
    '别急，先画因果图'
  ],
  executing: [
    '执行中：不要眨眼',
    '把任务切成小块逐个击破',
    '开始跑 pipeline',
    '一键推进：走你',
    '让结果自己说话',
    '先做最小可行，再做最美版本'
  ],
  syncing: [
    '同步中：把今天锁进云里',
    '备份不是仪式，是安全感',
    '写入中…别断电',
    '把变更交给时间戳',
    '云端对齐：咔哒',
    '同步完成前先别乱动',
    '把未来的自己从灾难里救出来',
    '多一份备份，少一份后悔'
  ],
  error: [
    '警报响了：先别慌',
    '我闻到 bug 的味道了',
    '先复现，再谈修复',
    '把日志给我，我会说人话',
    '错误不是敌人，是线索',
    '把影响面圈起来',
    '先止血，再手术',
    '我在：马上定位根因',
    '别怕，这种我见多了',
    '报警中：让问题自己现形'
  ],
  cat: [
    '喵~',
    '咕噜咕噜…',
    '尾巴摇一摇',
    '晒太阳最开心',
    '有人来看我啦',
    '我是这个办公室的吉祥物',
    '伸个懒腰',
    '今天的罐罐准备好了吗',
    '呼噜呼噜',
    '这个位置视野最好'
  ]
};

let game, star, sofa, serverroom, areas = {}, currentState = 'idle', pendingDesiredState = null, statusText, lastFetch = 0, lastBlink = 0, lastBubble = 0, targetX = 660, targetY = 170, bubble = null, typewriterText = '', typewriterTarget = '', typewriterIndex = 0, lastTypewriter = 0, syncAnimSprite = null, catBubble = null;
let isMoving = false;
let waypoints = [];
let lastWanderAt = 0;
let coordsOverlay, coordsDisplay, coordsToggle;
let showCoords = false;
const FETCH_INTERVAL = 2000;
const BLINK_INTERVAL = 2500;
const BUBBLE_INTERVAL = 8000;
const CAT_BUBBLE_INTERVAL = 18000;
let lastCatBubble = 0;
const TYPEWRITER_DELAY = 50;
let agents = {}; // agentId -> sprite/container
let economyData = {}; // agentId -> economy agent (tokens, status, contract)

function fetchEconomy() {
  fetch('/economy?t=' + Date.now(), { cache: 'no-store' })
    .then(r => r.json())
    .then(data => {
      if (!Array.isArray(data)) return;
      economyData = {};
      for (const a of data) economyData[a.id] = a;
      // refresh token badges on existing agents
      for (const [agentId, container] of Object.entries(agents)) {
        updateTokenBadge(container, economyData[agentId]);
      }
    })
    .catch(() => {});
}

function updateTokenBadge(container, econ) {
  // find or create token badge (index 3 in container children)
  let badge = container.list ? container.list.find(c => c.name === 'tokenBadge') : null;
  if (!econ) {
    if (badge) badge.setVisible(false);
    return;
  }
  const tokens = econ.tokens ?? '?';
  const label = '💰' + tokens;
  if (!badge) {
    badge = game.add.text(0, -54, label, {
      fontFamily: 'ArkPixel, monospace',
      fontSize: '11px',
      fill: '#fbbf24',
      stroke: '#000',
      strokeThickness: 2,
      backgroundColor: 'rgba(0,0,0,0.6)',
      padding: { x: 3, y: 1 }
    }).setOrigin(0.5);
    badge.name = 'tokenBadge';
    container.add(badge);
  } else {
    badge.setText(label);
    badge.setVisible(true);
  }
}
let lastAgentsFetch = 0;
const AGENTS_FETCH_INTERVAL = 2500;

// agent 颜色配置
const AGENT_COLORS = {
  star: 0xffd700,
  npc1: 0x00aaff,
  agent_nika: 0xff69b4,
  default: 0x94a3b8
};

// agent 名字颜色
const NAME_TAG_COLORS = {
  approved: 0x22c55e,
  pending: 0xf59e0b,
  rejected: 0xef4444,
  offline: 0x64748b,
  default: 0x1f2937
};

// breakroom / writing / error 区域的 agent 分布位置（多 agent 时错开）
const AREA_POSITIONS = {
  breakroom: [
    { x: 620, y: 180 },
    { x: 560, y: 220 },
    { x: 680, y: 210 }
  ],
  writing: [
    { x: 760, y: 320 },
    { x: 830, y: 280 },
    { x: 690, y: 350 }
  ],
  error: [
    { x: 180, y: 260 },
    { x: 120, y: 220 },
    { x: 240, y: 230 }
  ]
};

let areaPositionCounters = { breakroom: 0, writing: 0, error: 0 };


// 状态控制栏函数（用于测试）
function setState(state, detail) {
  fetch('/set_state', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ state, detail })
  }).then(() => fetchStatus());
}

// 初始化：先检测 WebP 支持，再启动游戏
async function initGame() {
  try {
    supportsWebP = await checkWebPSupport();
  } catch (e) {
    try {
      supportsWebP = await checkWebPSupportFallback();
    } catch (e2) {
      supportsWebP = false;
    }
  }

  console.log('WebP 支持:', supportsWebP);
  new Phaser.Game(config);
}

function preload() {
  loadingOverlay = document.getElementById('loading-overlay');
  loadingProgressBar = document.getElementById('loading-progress-bar');
  loadingText = document.getElementById('loading-text');
  loadingProgressContainer = document.getElementById('loading-progress-container');

  // 从 LAYOUT 读取总资源数量（避免 magic number）
  totalAssets = LAYOUT.totalAssets || 15;
  loadedAssets = 0;

  this.load.on('filecomplete', () => {
    updateLoadingProgress();
  });

  this.load.on('complete', () => {
    hideLoadingOverlay();
  });

  this.load.image('office_bg', '/static/office_bg_small' + (supportsWebP ? '.webp' : '.png') + '?v={{VERSION_TIMESTAMP}}');
  this.load.spritesheet('star_idle', '/static/star-idle-spritesheet' + getExt('star-idle-spritesheet.png'), { frameWidth: 128, frameHeight: 128 });
  this.load.spritesheet('star_researching', '/static/star-researching-spritesheet' + getExt('star-researching-spritesheet.png'), { frameWidth: 128, frameHeight: 105 });

  this.load.image('sofa_idle', '/static/sofa-idle' + getExt('sofa-idle.png'));
  this.load.spritesheet('sofa_busy', '/static/sofa-busy-spritesheet' + getExt('sofa-busy-spritesheet.png'), { frameWidth: 256, frameHeight: 256 });

  this.load.spritesheet('plants', '/static/plants-spritesheet' + getExt('plants-spritesheet.png'), { frameWidth: 160, frameHeight: 160 });
  this.load.spritesheet('posters', '/static/posters-spritesheet' + getExt('posters-spritesheet.png'), { frameWidth: 160, frameHeight: 160 });
  this.load.spritesheet('coffee_machine', '/static/coffee-machine-spritesheet' + getExt('coffee-machine-spritesheet.png'), { frameWidth: 230, frameHeight: 230 });
  this.load.spritesheet('serverroom', '/static/serverroom-spritesheet' + getExt('serverroom-spritesheet.png'), { frameWidth: 180, frameHeight: 251 });

  this.load.spritesheet('error_bug', '/static/error-bug-spritesheet-grid' + (supportsWebP ? '.webp' : '.png'), { frameWidth: 180, frameHeight: 180 });
  this.load.spritesheet('cats', '/static/cats-spritesheet' + (supportsWebP ? '.webp' : '.png'), { frameWidth: 160, frameHeight: 160 });
  this.load.image('desk', '/static/desk' + getExt('desk.png'));
  this.load.spritesheet('star_working', '/static/star-working-spritesheet-grid' + (supportsWebP ? '.webp' : '.png'), { frameWidth: 230, frameHeight: 144 });
  this.load.spritesheet('sync_anim', '/static/sync-animation-spritesheet-grid' + (supportsWebP ? '.webp' : '.png'), { frameWidth: 256, frameHeight: 256 });
  this.load.image('memo_bg', '/static/memo-bg' + (supportsWebP ? '.webp' : '.png'));

  // 新办公桌：强制 PNG（透明）
  this.load.image('desk_v2', '/static/desk-v2.png');
  this.load.spritesheet('flowers', '/static/flowers-spritesheet' + (supportsWebP ? '.webp' : '.png'), { frameWidth: 65, frameHeight: 65 });
}

function create() {
  game = this;
  this.add.image(640, 360, 'office_bg');

  areas = LAYOUT.areas;

  // === 萝卜：会走动的马 🐎 ===
  // 用 Phaser Container 包住 emoji + 名字标签，复用 star 的移动逻辑
  const horseContainer = game.add.container(areas.breakroom.x, areas.breakroom.y);
  horseContainer.setDepth(20);

  const horseEmoji = game.add.text(0, 0, '🐎', {
    fontFamily: 'ArkPixel, monospace, Apple Color Emoji, Segoe UI Emoji',
    fontSize: '36px',
  }).setOrigin(0.5, 0.8);
  horseEmoji.name = 'horseEmoji';

  const horseLabel = game.add.text(0, -38, '萝卜', {
    fontFamily: 'ArkPixel, monospace',
    fontSize: '13px',
    fill: '#ffd700',
    stroke: '#000',
    strokeThickness: 3,
    backgroundColor: 'rgba(0,0,0,0.5)',
    padding: { x: 4, y: 2 }
  }).setOrigin(0.5);
  horseLabel.name = 'horseLabel';

  horseContainer.add([horseEmoji, horseLabel]);
  window.horseContainer = horseContainer;

  // Shim: make 'star' point to horseContainer so all existing movement code works
  star = {
    x: horseContainer.x,
    y: horseContainer.y,
    setPosition: (x, y) => { horseContainer.setPosition(x, y); star.x = x; star.y = y; },
    setY: (y) => { horseContainer.setPosition(horseContainer.x, y); star.y = y; },
    setVisible: (v) => horseContainer.setVisible(true), // 马永远可见
    setAlpha: () => {},
    setDepth: (d) => horseContainer.setDepth(d),
    setScale: () => {},
    anims: { play: () => {}, stop: () => {}, isPlaying: false },
    body: { velocity: { x: 0, y: 0 }, setVelocity: (vx, vy) => {} },
    _horseFlipTimer: 0,
    _lastVx: 0,
  };

  // Horse emoji flip on direction change
  window._horseLastX = horseContainer.x;
  window._horseFlipInterval = setInterval(() => {
    const dx = horseContainer.x - window._horseLastX;
    if (Math.abs(dx) > 1) {
      horseEmoji.setFlipX(dx < 0);
    }
    window._horseLastX = horseContainer.x;
  }, 100);

  // Dummy sofa ref (referenced in state change code)
  sofa = { setTexture: () => {}, anims: { play: () => {}, stop: () => {} }, setVisible: () => {} };

  // === 牌匾（来自 LAYOUT）===
  const plaqueX = LAYOUT.plaque.x;
  const plaqueY = LAYOUT.plaque.y;
  const plaqueBg = game.add.rectangle(plaqueX, plaqueY, LAYOUT.plaque.width, LAYOUT.plaque.height, 0x5d4037);
  plaqueBg.setStrokeStyle(3, 0x3e2723);
  const plaqueText = game.add.text(plaqueX, plaqueY, '萝卜的西部马厩', {
    fontFamily: 'ArkPixel, monospace',
    fontSize: '18px',
    fill: '#ffd700',
    fontWeight: 'bold',
    stroke: '#000',
    strokeThickness: 2
  }).setOrigin(0.5);
  game.add.text(plaqueX - 190, plaqueY, '⭐', { fontFamily: 'ArkPixel, monospace', fontSize: '20px' }).setOrigin(0.5);
  game.add.text(plaqueX + 190, plaqueY, '⭐', { fontFamily: 'ArkPixel, monospace', fontSize: '20px' }).setOrigin(0.5);

  // === 服务器区保留（闪灯效果）===
  this.anims.create({
    key: 'serverroom_on',
    frames: this.anims.generateFrameNumbers('serverroom', { start: 0, end: 39 }),
    frameRate: 6,
    repeat: -1
  });
  serverroom = this.add.sprite(
    LAYOUT.furniture.serverroom.x,
    LAYOUT.furniture.serverroom.y,
    'serverroom',
    0
  ).setOrigin(LAYOUT.furniture.serverroom.origin.x, LAYOUT.furniture.serverroom.origin.y);
  serverroom.setDepth(LAYOUT.furniture.serverroom.depth);
  serverroom.anims.stop();
  serverroom.setFrame(0);

  // === Star 在桌前工作（来自 LAYOUT）===
  this.anims.create({
    key: 'star_working',
    frames: this.anims.generateFrameNumbers('star_working', { start: 0, end: 191 }),
    frameRate: 12,
    repeat: -1
  });
  this.anims.create({
    key: 'error_bug',
    frames: this.anims.generateFrameNumbers('error_bug', { start: 0, end: 95 }),
    frameRate: 12,
    repeat: -1
  });

  // === 错误 bug（来自 LAYOUT）===
  const errorBug = this.add.sprite(
    LAYOUT.furniture.errorBug.x,
    LAYOUT.furniture.errorBug.y,
    'error_bug',
    0
  ).setOrigin(LAYOUT.furniture.errorBug.origin.x, LAYOUT.furniture.errorBug.origin.y);
  errorBug.setDepth(LAYOUT.furniture.errorBug.depth);
  errorBug.setVisible(false);
  errorBug.setScale(LAYOUT.furniture.errorBug.scale);
  errorBug.anims.play('error_bug', true);
  window.errorBug = errorBug;
  window.errorBugDir = 1;

  // starWorking sprite removed — horse (萝卜) is the main character now
  window.starWorking = { setVisible: () => {}, anims: { play: () => {}, stop: () => {} } };

  // === 同步动画（来自 LAYOUT）===
  this.anims.create({
    key: 'sync_anim',
    frames: this.anims.generateFrameNumbers('sync_anim', { start: 1, end: 52 }),
    frameRate: 12,
    repeat: -1
  });
  syncAnimSprite = this.add.sprite(
    LAYOUT.furniture.syncAnim.x,
    LAYOUT.furniture.syncAnim.y,
    'sync_anim',
    0
  ).setOrigin(LAYOUT.furniture.syncAnim.origin.x, LAYOUT.furniture.syncAnim.origin.y);
  syncAnimSprite.setDepth(LAYOUT.furniture.syncAnim.depth);
  syncAnimSprite.anims.stop();
  syncAnimSprite.setFrame(0);

  window.starSprite = star;

  statusText = document.getElementById('status-text');
  coordsOverlay = document.getElementById('coords-overlay');
  coordsDisplay = document.getElementById('coords-display');
  coordsToggle = document.getElementById('coords-toggle');

  coordsToggle.addEventListener('click', () => {
    showCoords = !showCoords;
    coordsOverlay.style.display = showCoords ? 'block' : 'none';
    coordsToggle.textContent = showCoords ? '隐藏坐标' : '显示坐标';
    coordsToggle.style.background = showCoords ? '#e94560' : '#333';
  });

  game.input.on('pointermove', (pointer) => {
    if (!showCoords) return;
    const x = Math.max(0, Math.min(config.width - 1, Math.round(pointer.x)));
    const y = Math.max(0, Math.min(config.height - 1, Math.round(pointer.y)));
    coordsDisplay.textContent = `${x}, ${y}`;
    coordsOverlay.style.left = (pointer.x + 18) + 'px';
    coordsOverlay.style.top = (pointer.y + 18) + 'px';
  });

  loadMemo();
  fetchStatus();
  // 先强制加一个测试用的尼卡 agent 渲染
  const testNika = {
    agentId: 'agent_nika',
    name: '尼卡',
    isMain: false,
    state: 'writing',
    detail: '在画像素画...',
    area: 'writing',
    authStatus: 'approved',
    updated_at: new Date().toISOString()
  };
  renderAgent(testNika);
  fetchAgents();

  // 测试用：让尼卡模拟走来走去
  window.testNikaState = 'writing';
  window.testNikaTimer = setInterval(() => {
    const states = ['idle', 'writing', 'researching', 'executing'];
    const areas = { idle: 'breakroom', writing: 'writing', researching: 'writing', executing: 'writing' };
    window.testNikaState = states[Math.floor(Math.random() * states.length)];
    const testAgent = {
      agentId: 'agent_nika',
      name: '尼卡',
      isMain: false,
      state: window.testNikaState,
      detail: '在画像素画...',
      area: areas[window.testNikaState],
      authStatus: 'approved',
      updated_at: new Date().toISOString()
    };
    renderAgent(testAgent);
  }, 5000);
}

function update(time) {
  if (time - lastFetch > FETCH_INTERVAL) { fetchStatus(); lastFetch = time; }
  if (time - lastAgentsFetch > AGENTS_FETCH_INTERVAL) { fetchAgents(); fetchEconomy(); lastAgentsFetch = time; }

  const effectiveStateForServer = pendingDesiredState || currentState;
  if (serverroom) {
    if (effectiveStateForServer === 'idle') {
      if (serverroom.anims.isPlaying) {
        serverroom.anims.stop();
        serverroom.setFrame(0);
      }
    } else {
      if (!serverroom.anims.isPlaying || serverroom.anims.currentAnim?.key !== 'serverroom_on') {
        serverroom.anims.play('serverroom_on', true);
      }
    }
  }

  if (window.errorBug) {
    if (effectiveStateForServer === 'error') {
      window.errorBug.setVisible(true);
      if (!window.errorBug.anims.isPlaying || window.errorBug.anims.currentAnim?.key !== 'error_bug') {
        window.errorBug.anims.play('error_bug', true);
      }
      const leftX = LAYOUT.furniture.errorBug.pingPong.leftX;
      const rightX = LAYOUT.furniture.errorBug.pingPong.rightX;
      const speed = LAYOUT.furniture.errorBug.pingPong.speed;
      const dir = window.errorBugDir || 1;
      window.errorBug.x += speed * dir;
      window.errorBug.y = LAYOUT.furniture.errorBug.y;
      if (window.errorBug.x >= rightX) {
        window.errorBug.x = rightX;
        window.errorBugDir = -1;
      } else if (window.errorBug.x <= leftX) {
        window.errorBug.x = leftX;
        window.errorBugDir = 1;
      }
    } else {
      window.errorBug.setVisible(false);
      window.errorBug.anims.stop();
    }
  }

  if (syncAnimSprite) {
    if (effectiveStateForServer === 'syncing') {
      if (!syncAnimSprite.anims.isPlaying || syncAnimSprite.anims.currentAnim?.key !== 'sync_anim') {
        syncAnimSprite.anims.play('sync_anim', true);
      }
    } else {
      if (syncAnimSprite.anims.isPlaying) syncAnimSprite.anims.stop();
      syncAnimSprite.setFrame(0);
    }
  }

  if (time - lastBubble > BUBBLE_INTERVAL) {
    showBubble();
    lastBubble = time;
  }
  if (time - lastCatBubble > CAT_BUBBLE_INTERVAL) {
    showCatBubble();
    lastCatBubble = time;
  }

  if (typewriterIndex < typewriterTarget.length && time - lastTypewriter > TYPEWRITER_DELAY) {
    typewriterText += typewriterTarget[typewriterIndex];
    statusText.textContent = typewriterText;
    typewriterIndex++;
    lastTypewriter = time;
  }

  moveStar(time);
}

function normalizeState(s) {
  if (!s) return 'idle';
  if (s === 'working') return 'writing';
  if (s === 'run' || s === 'running') return 'executing';
  if (s === 'sync') return 'syncing';
  if (s === 'research') return 'researching';
  return s;
}

function fetchStatus() {
  fetch('/status')
    .then(response => response.json())
    .then(data => {
      const nextState = normalizeState(data.state);
      const stateInfo = STATES[nextState] || STATES.idle;
      const changed = (pendingDesiredState === null) && (nextState !== currentState);
      const nextLine = '[' + stateInfo.name + '] ' + (data.detail || '...');
      if (changed) {
        typewriterTarget = nextLine;
        typewriterText = '';
        typewriterIndex = 0;

        pendingDesiredState = null;
        currentState = nextState;

        if (nextState === 'idle') {
          if (game.textures.exists('sofa_busy')) {
            sofa.setTexture('sofa_busy');
            sofa.anims.play('sofa_busy', true);
          }
          star.setVisible(false);
          star.anims.stop();
          if (window.starWorking) {
            window.starWorking.setVisible(false);
            window.starWorking.anims.stop();
          }
        } else if (nextState === 'error') {
          sofa.anims.stop();
          sofa.setTexture('sofa_idle');
          star.setVisible(false);
          star.anims.stop();
          if (window.starWorking) {
            window.starWorking.setVisible(false);
            window.starWorking.anims.stop();
          }
        } else if (nextState === 'syncing') {
          sofa.anims.stop();
          sofa.setTexture('sofa_idle');
          star.setVisible(false);
          star.anims.stop();
          if (window.starWorking) {
            window.starWorking.setVisible(false);
            window.starWorking.anims.stop();
          }
        } else {
          sofa.anims.stop();
          sofa.setTexture('sofa_idle');
          star.setVisible(false);
          star.anims.stop();
          if (window.starWorking) {
            window.starWorking.setVisible(true);
            window.starWorking.anims.play('star_working', true);
          }
        }

        if (serverroom) {
          if (nextState === 'idle') {
            serverroom.anims.stop();
            serverroom.setFrame(0);
          } else {
            serverroom.anims.play('serverroom_on', true);
          }
        }

        if (syncAnimSprite) {
          if (nextState === 'syncing') {
            if (!syncAnimSprite.anims.isPlaying || syncAnimSprite.anims.currentAnim?.key !== 'sync_anim') {
              syncAnimSprite.anims.play('sync_anim', true);
            }
          } else {
            if (syncAnimSprite.anims.isPlaying) syncAnimSprite.anims.stop();
            syncAnimSprite.setFrame(0);
          }
        }
      } else {
        if (!typewriterTarget || typewriterTarget !== nextLine) {
          typewriterTarget = nextLine;
          typewriterText = '';
          typewriterIndex = 0;
        }
      }
    })
    .catch(error => {
      typewriterTarget = '连接失败，正在重试...';
      typewriterText = '';
      typewriterIndex = 0;
    });
}

function moveStar(time) {
  const effectiveState = pendingDesiredState || currentState;
  const stateInfo = STATES[effectiveState] || STATES.idle;
  const baseTarget = areas[stateInfo.area] || areas.breakroom;

  const dx = targetX - star.x;
  const dy = targetY - star.y;
  const dist = Math.sqrt(dx * dx + dy * dy);
  const speed = 1.4;
  const wobble = Math.sin(time / 200) * 0.8;

  if (dist > 3) {
    const newX = star.x + (dx / dist) * speed;
    const newY = star.y + (dy / dist) * speed + wobble;
    star.setPosition(newX, newY);
    // flip horse based on movement direction
    if (window.horseContainer) {
      const emoji = window.horseContainer.list.find(c => c.name === 'horseEmoji');
      if (emoji) emoji.setFlipX(dx < 0);
    }
    isMoving = true;
  } else {
    if (waypoints && waypoints.length > 0) {
      waypoints.shift();
      if (waypoints.length > 0) {
        targetX = waypoints[0].x;
        targetY = waypoints[0].y;
        isMoving = true;
      } else {
        if (pendingDesiredState !== null) {
          isMoving = false;
          currentState = pendingDesiredState;
          pendingDesiredState = null;

          if (currentState === 'idle') {
            star.setVisible(false);
            star.anims.stop();
            if (window.starWorking) {
              window.starWorking.setVisible(false);
              window.starWorking.anims.stop();
            }
          } else {
            star.setVisible(false);
            star.anims.stop();
            if (window.starWorking) {
              window.starWorking.setVisible(true);
              window.starWorking.anims.play('star_working', true);
            }
          }
        }
      }
    } else {
      if (pendingDesiredState !== null) {
        isMoving = false;
        currentState = pendingDesiredState;
        pendingDesiredState = null;

        if (currentState === 'idle') {
          star.setVisible(false);
          star.anims.stop();
          if (window.starWorking) {
            window.starWorking.setVisible(false);
            window.starWorking.anims.stop();
          }
          if (game.textures.exists('sofa_busy')) {
            sofa.setTexture('sofa_busy');
            sofa.anims.play('sofa_busy', true);
          }
        } else {
          star.setVisible(false);
          star.anims.stop();
          if (window.starWorking) {
            window.starWorking.setVisible(true);
            window.starWorking.anims.play('star_working', true);
          }
          sofa.anims.stop();
          sofa.setTexture('sofa_idle');
        }
      }
    }
  }
}

function showBubble() {
  if (bubble) { bubble.destroy(); bubble = null; }
  const texts = BUBBLE_TEXTS[currentState] || BUBBLE_TEXTS.idle;
  if (currentState === 'idle') return;

  let anchorX = star.x;
  let anchorY = star.y;
  if (currentState === 'syncing' && syncAnimSprite && syncAnimSprite.visible) {
    anchorX = syncAnimSprite.x;
    anchorY = syncAnimSprite.y;
  } else if (currentState === 'error' && window.errorBug && window.errorBug.visible) {
    anchorX = window.errorBug.x;
    anchorY = window.errorBug.y;
  } else if (!star.visible && window.starWorking && window.starWorking.visible) {
    anchorX = window.starWorking.x;
    anchorY = window.starWorking.y;
  }

  const text = texts[Math.floor(Math.random() * texts.length)];
  const bubbleY = anchorY - 70;
  const bg = game.add.rectangle(anchorX, bubbleY, text.length * 10 + 20, 28, 0xffffff, 0.95);
  bg.setStrokeStyle(2, 0x000000);
  const txt = game.add.text(anchorX, bubbleY, text, { fontFamily: 'ArkPixel, monospace', fontSize: '12px', fill: '#000', align: 'center' }).setOrigin(0.5);
  bubble = game.add.container(0, 0, [bg, txt]);
  bubble.setDepth(1200);
  setTimeout(() => { if (bubble) { bubble.destroy(); bubble = null; } }, 3000);
}

function showCatBubble() {
  if (!window.catSprite) return;
  if (window.catBubble) { window.catBubble.destroy(); window.catBubble = null; }
  const texts = BUBBLE_TEXTS.cat || ['喵~', '咕噜咕噜…'];
  const text = texts[Math.floor(Math.random() * texts.length)];
  const anchorX = window.catSprite.x;
  const anchorY = window.catSprite.y - 60;
  const bg = game.add.rectangle(anchorX, anchorY, text.length * 10 + 20, 24, 0xfffbeb, 0.95);
  bg.setStrokeStyle(2, 0xd4a574);
  const txt = game.add.text(anchorX, anchorY, text, { fontFamily: 'ArkPixel, monospace', fontSize: '11px', fill: '#8b6914', align: 'center' }).setOrigin(0.5);
  window.catBubble = game.add.container(0, 0, [bg, txt]);
  window.catBubble.setDepth(2100);
  setTimeout(() => { if (window.catBubble) { window.catBubble.destroy(); window.catBubble = null; } }, 4000);
}

function fetchAgents() {
  fetch('/agents?t=' + Date.now(), { cache: 'no-store' })
    .then(response => response.json())
    .then(data => {
      if (!Array.isArray(data)) return;
      // 重置位置计数器
      areaPositionCounters = { breakroom: 0, writing: 0, error: 0 };
      // 处理每个 agent
      for (let agent of data) {
        renderAgent(agent);
      }
      // 移除不再存在的 agent
      const currentIds = new Set(data.map(a => a.agentId));
      for (let id in agents) {
        if (!currentIds.has(id)) {
          if (agents[id]) {
            agents[id].destroy();
            delete agents[id];
          }
        }
      }
    })
    .catch(error => {
      console.error('拉取 agents 失败:', error);
    });
}

function getAreaPosition(area) {
  const positions = AREA_POSITIONS[area] || AREA_POSITIONS.breakroom;
  const idx = areaPositionCounters[area] || 0;
  areaPositionCounters[area] = (idx + 1) % positions.length;
  return positions[idx];
}

function renderAgent(agent) {
  const agentId = agent.agentId;
  const name = agent.name || 'Agent';
  const area = agent.area || 'breakroom';
  const authStatus = agent.authStatus || 'pending';
  const isMain = !!agent.isMain;

  // 获取这个 agent 在区域里的位置
  const pos = getAreaPosition(area);
  const baseX = pos.x;
  const baseY = pos.y;

  // 颜色
  const bodyColor = AGENT_COLORS[agentId] || AGENT_COLORS.default;
  const nameColor = NAME_TAG_COLORS[authStatus] || NAME_TAG_COLORS.default;

  // 透明度（离线/待批准/拒绝时变半透明）
  let alpha = 1;
  if (authStatus === 'pending') alpha = 0.7;
  if (authStatus === 'rejected') alpha = 0.4;
  if (authStatus === 'offline') alpha = 0.5;

  if (!agents[agentId]) {
    // 新建 agent
    const container = game.add.container(baseX, baseY);
    container.setDepth(1200 + (isMain ? 100 : 0)); // 放到最顶层！

    // 像素小人：用星星图标，更明显
    const starIcon = game.add.text(0, 0, '⭐', {
      fontFamily: 'ArkPixel, monospace',
      fontSize: '32px'
    }).setOrigin(0.5);
    starIcon.name = 'starIcon';

    // 名字标签（漂浮）
    const nameTag = game.add.text(0, -36, name, {
      fontFamily: 'ArkPixel, monospace',
      fontSize: '14px',
      fill: '#' + nameColor.toString(16).padStart(6, '0'),
      stroke: '#000',
      strokeThickness: 3,
      backgroundColor: 'rgba(255,255,255,0.95)'
    }).setOrigin(0.5);
    nameTag.name = 'nameTag';

    // 状态小点（绿色/黄色/红色）
    let dotColor = 0x64748b;
    if (authStatus === 'approved') dotColor = 0x22c55e;
    if (authStatus === 'pending') dotColor = 0xf59e0b;
    if (authStatus === 'rejected') dotColor = 0xef4444;
    if (authStatus === 'offline') dotColor = 0x94a3b8;
    const statusDot = game.add.circle(20, -20, 5, dotColor, alpha);
    statusDot.setStrokeStyle(2, 0x000000, alpha);
    statusDot.name = 'statusDot';

    container.add([starIcon, statusDot, nameTag]);
    agents[agentId] = container;
    updateTokenBadge(container, economyData[agentId]);
  } else {
    // 更新 agent
    const container = agents[agentId];
    container.setPosition(baseX, baseY);
    container.setAlpha(alpha);
    container.setDepth(1200 + (isMain ? 100 : 0));

    // 更新名字和颜色（如果变化）
    const nameTag = container.getAt(2);
    if (nameTag && nameTag.name === 'nameTag') {
      nameTag.setText(name);
      nameTag.setFill('#' + (NAME_TAG_COLORS[authStatus] || NAME_TAG_COLORS.default).toString(16).padStart(6, '0'));
    }
    // 更新状态点颜色
    const statusDot = container.getAt(1);
    if (statusDot && statusDot.name === 'statusDot') {
      let dotColor = 0x64748b;
      if (authStatus === 'approved') dotColor = 0x22c55e;
      if (authStatus === 'pending') dotColor = 0xf59e0b;
      if (authStatus === 'rejected') dotColor = 0xef4444;
      if (authStatus === 'offline') dotColor = 0x94a3b8;
      statusDot.fillColor = dotColor;
    }
  }
}

// 启动游戏
initGame();
