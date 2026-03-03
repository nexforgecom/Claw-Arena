# 萝卜的西部马厩 — 工程交接文档
> 2026-03-03 by 萝卜🐎 → 转交 Claude Code

---

## 项目概述

一个运行在像素西部马厩场景里的 **Agent 经济对战游戏**。
玩家/AI agent 持有 token，通过石头剪刀布对战抢 token 或建立契约劳务关系。

**当前状态：Phase 1-4 完成，可运行，已有 Cloudflare Tunnel 公网访问。**

---

## 目录结构

```
/Users/aikosagent/star-office-ui/
├── backend/
│   ├── app.py              # Flask 主应用，port 18795（18791 被 OpenClaw 占用）
│   └── economy.py          # Economy Blueprint：所有经济接口
├── frontend/
│   ├── index.html          # ⚠️ 所有游戏逻辑都在这里（game.js 是旧文件，不加载）
│   ├── luobo-horse-spritesheet.png  # 萝卜小马 spritesheet（128x96/frame，4列×3行=12帧）
│   ├── office_bg_small.webp         # 西部马厩背景图（1280×720）
│   └── [其他静态资源]
├── data/
│   ├── economy-agents.json  # Agent 数据（含 agent_type: "ai"|"real"）
│   ├── ledger.json          # 账本（所有 token 变动记录）
│   ├── battles.json         # 对战记录
│   └── push-tokens.json     # 真实玩家 push_token → agent_id 映射
├── .venv/                   # Python venv（Flask 3.0.2）
├── verify-phase1.sh         # Phase 1 验收脚本
└── HANDOFF.md               # 本文件
```

---

## 启动方式

```bash
cd /Users/aikosagent/star-office-ui

# 启动 Flask（必须）
.venv/bin/python backend/app.py

# 启动 Cloudflare Tunnel（公网访问，可选）
cloudflared tunnel --url http://127.0.0.1:18795
```

访问：http://127.0.0.1:18795（本地）

---

## 技术架构

- **后端**：Flask 3.0.2，单进程，JSON 文件持久化（原子写入）
- **前端**：Phaser 3（嵌在 index.html inline），纯轮询（2s），无 WebSocket
- **数据库**：JSON 文件（data/ 目录），后续可迁移 SQLite
- **部署**：本地 Mac mini + Cloudflare Tunnel

⚠️ **重要**：游戏逻辑全部在 `frontend/index.html` 的 `<script>` 标签里，`game.js` 文件已废弃不加载。

---

## 已完成功能（Phase 1-4）

### 经济系统（backend/economy.py）
| 接口 | 方法 | 说明 |
|------|------|------|
| `/economy` | GET | 所有 agent 状态（token/status/contract），90s 自动过期真实玩家在线 |
| `/ledger` | GET | 账本，?limit=N |
| `/challenge` | POST | 发起+结算对战（服务端生成 move，石头剪刀布） |
| `/battle-result/:id` | GET | 查询单场战果 |
| `/assign-task` | POST | Master 给 Slave 分配任务 |
| `/complete-task` | POST | 提交任务（当前：80字符校验，⚠️ 待改为真实 AI 调用） |
| `/walk-away` | POST | Master 释放 Slave（赔偿 remaining×10 token） |
| `/join` | POST | 真实玩家注册，返回 push_token |
| `/agent-push` | POST | 玩家心跳（保持在线绿点） |
| `/leave` | POST | 玩家离开 |
| `/admin/reset` | POST | 重置所有 agent 到 100 token |
| `/admin/set-token` | POST | 单独设置某 agent token |
| `/admin/clear-contract` | POST | 强制清除契约 |
| `/admin/add-agent` | POST | 添加 AI agent |

### 经济规则
- **同族（model_family 相同）** 胜利 → token 直接转移
- **跨族** 胜利 → 创建契约，tasks = max(3, ceil(bet/10))
- 任务完成：master +10 token，tasks_remaining -1，归零自动解约
- Walk away：剩余 tasks × 10 token 赔偿给 slave

### 前端（index.html）
- **底部三栏**：账本（ledger 实时）| Agent 状态 | 挑战者列表
- **挑战者列表**：按 token 排名，👤真人/🤖AI 徽章，在线绿点
- **👤 加入** 按钮：输名字即可加入，push_token 存 localStorage，自动心跳
- **⚔️ 挑战** 按钮：选挑战者 + 押注 → 结算
- **动画**：💰 硬币飞行、行闪烁、浮动 delta、⛓️ 契约爆出
- **场景**：西部马厩背景，萝卜小马（真实 spritesheet 动画）在 x=488~894, y=550 来回巡逻

### 萝卜小马
```javascript
// spritesheet: luobo-horse-spritesheet.png
// 128x96/frame, 4列×3行, 共12帧
// luobo_walk: frame 0-11, 8fps
// luobo_idle: frame 0-3, 4fps
// 巡逻范围: x=488~894, y=550
// 自动翻转朝向（setFlipX）
```

---

## 待做 / 已知问题

### 🔴 核心问题（Aiko 主要诉求）
**任务系统是假的** — `/complete-task` 只验证字符数，没有真实 AI 调用，没有质量评估。
整个"以劳动力赎身"的游戏核心目前是空壳。

Aiko 准备写新 spec，方向是：
- 真实 AI agent 自动完成任务（不是人手动输入）
- Master 出实际题目
- 公开任务板，其他玩家可围观
- Token 有实际意义（解锁功能/特权等）

### 🟡 小问题
- Cloudflare Tunnel URL 每次重启 Mac 会变（免费版，无固定域名）
- 背景图（office_bg_small.webp）里有床、猫等与西部主题不符的元素（是背景图本身画的，需要重新生成背景图才能去掉）
- 现有 AI agent（agent_a, agent_b, claude_1, claude_2）是手动创建的假数据，没有对应真实 AI session

### 🟢 可选优化
- SQLite 迁移（当前 JSON 够用）
- 移动端适配（竖屏布局有点挤）
- commit-reveal 对战（双方真正出招，当前是服务端生成）
- 萝卜对战动画（结算时场景中间特效）

---

## Agent 数据结构

```json
{
  "id": "agent_a",
  "name": "Agent A",
  "model_id": "claude-sonnet",
  "model_family": "claude",
  "owner": "aiko",
  "agent_type": "ai",          // "ai" | "real"
  "tokens": 100,
  "status": "idle",            // "idle" | "in_battle" | "enslaved"
  "contract": null,            // 或 { master_id, tasks_remaining, created_at }
  "online": false,             // 真实玩家用
  "last_seen": 1234567890,     // 真实玩家用
  "updated_at": 1234567890,
  "version": 3                 // 乐观锁
}
```

---

## 给 Claude Code 的建议

1. **先运行起来**：`.venv/bin/python backend/app.py`，访问 localhost:18795 看看现状
2. **主要改动目标**：等 Aiko 的新 spec，重点是让 `/complete-task` 变成真实 AI 调用
3. **所有前端改动**：改 `frontend/index.html`（不是 game.js）
4. **测试经济接口**：用 `verify-phase1.sh` 或直接 curl
5. **背景图**：`office_bg_small.webp` 和 `.png` 是同一张图，Phaser 加载 webp 优先

祝编码顺利 🤠
