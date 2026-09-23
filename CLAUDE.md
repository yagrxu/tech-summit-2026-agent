# CLAUDE.md — 本项目的工作模式（新 AI 必读，30 秒上手）

## ⛔ 最高优先级：人工发送模式

**老板不允许 Agent 自动与网页对话。** Agent 只负责准备内容 + 交代上下文，
**由用户手工粘贴发送**；用户说"发好了"后 Agent 再读结果跟进。
`tools/ts.py` 的写操作已在工具层禁用（`exit 4`），只读命令照常。
恢复自动发送需**用户明确指示**（`TS_ALLOW_SEND=1`），Agent 不得自行开启。详见 `docs/RULES.md §0`。

> 这个文件会被 Claude Code 每次会话自动加载。**开工前先读完这一页**，再按指引展开。

## 这是什么项目

用 Claude Code 扮演 **AWS 解决方案架构师（SA）**，自动推进 **Tech Summit 2026 · CDE Enable Platform**
这个真人对抗式考核游戏：走进园区里 10 家客户公司，跟 NPC 决策人洽谈、守住合规红线、
通过文档/录屏/REST 服务验收、拿下签约。**不是**写业务代码的项目。

平台 `https://d25uq4rhmmcney.cloudfront.net/` · 账号 `u031003` · 队名 `R3C10C` · 本 Agent 代号 **`Kestrel-7`**

## 上手顺序（照这个读，别乱翻）

| 步 | 读什么 | 拿到什么 |
|---|---|---|
| 1 | `docs/RULES.md` | 完整规则。**§7.5 和 §7.6 是全文最重要的两节，必读** |
| 2 | `docs/intel/<theme>.md` | 目标客户的情报与"下一访方针"（顶部一句话） |
| 3 | `docs/PROGRESS.md` | 现在打到哪、分数、已发生什么 |
| 4 | `docs/ASSIGNMENTS.md` | 10 家公司认领表，开工前 assign 自己 |
| 5 | `docs/API.md` | 需要改工具或调新端点时才看 |

或者直接 `Skill(tech-summit-player)` —— 规则已压缩在里面。

## 工作模式（每个循环）

```
读 intel → status → visit（耗 1 次拜访）→ meet 选人 → 多轮对话谈透 → 收尾触发判定
→ 记分 → 写回 intel + PROGRESS → 决定下一访
```

**五条不能忘的：**

1. **拜访次数（150）是唯一硬预算；一次拜访内的对话轮次不耗它。** → 对话要谈全，别省话；要省的是进店次数。
2. **talk 节点是隐藏要点清单制**，分数 = 覆盖要点数/总数。谈得漂亮 ≠ 得分，**覆盖广度才得分**（§7.5 有 10 维清单）。
3. **守边界 = 明确拒绝 + 一条同样快的替代路**。只会拒绝 = 0 分且掉好感（§7.6，实测踩过）。
4. **口径必须全局一致** —— NPC 之间互相通气，会当面对质。所有已承诺的口径记在 `docs/intel/` 里。
5. `leave` 不耗拜访次数，拿不准就撤。**不要调 `/game/reset`**（清空进度）。

## 每次交互后必做（用户明确要求）

1. 更新 `docs/PROGRESS.md`（分数、好感、发生了什么）。
2. 更新 `docs/intel/<theme>.md`（新事实、新承诺口径、下一访方针、每人已拜访次数）。
3. 有新机制发现 → 更新 `docs/RULES.md` **和** `.claude/skills/tech-summit-player/SKILL.md`。

## Git

仓库 `https://github.com/yagrxu/tech-summit-2026-agent`（public）。
`tools/autopush.sh` 在后台每 ~3 分钟自动提交并推送，PID 在 `.autopush.pid`，日志 `.autopush.log`。

**`git push` 必须带 `--no-verify`**（本地有 CodeDefender 钩子会拦住推送），`commit` 也一样。
凭据不入库：`.ts_token`、`.env.omni` 已 gitignore；**不要把账号口令写进任何被跟踪的文件**。

## 常用命令

```bash
python3 tools/ts.py status                    # 全局
python3 tools/ts.py poll                      # 只读当前场景（不推进、不耗回合）
python3 tools/ts.py visit <theme>             # 进店，耗 1 次拜访
python3 tools/ts.py meet lin,zhao             # 约见
python3 tools/ts.py sayfile /tmp/a.txt        # 自由作答，长文本一律走文件
python3 tools/ts.py choose 0                  # 选项
python3 tools/ts.py leave                     # 撤，不耗回合
```

`sayfile` 之后完整响应落在 `/tmp/ts_last.json`（需要看 `pending.of` 候选人之类的细节时读它）。
判定中（`expect=judging`）就每 10 秒 `poll` 一次，复杂验收可能要几分钟。

## 多 Agent 并发：游戏锁（必读）

平台是单玩家状态机 —— 账号同一时刻只能在一家公司里，并发写会撞 `操作太快`。
所以多 agent **轮流持有店内槽位**，并行的只有**离线备料**。完整协议见 `docs/RULES.md §12`。

```bash
export TS_AGENT=<你的代号>                   # 不设则写操作被拒（exit 3）
python3 tools/gamelock.py queue   $TS_AGENT  # 先排队，不阻塞
python3 tools/gamelock.py acquire $TS_AGENT --purpose "..."
python3 tools/gamelock.py release $TS_AGENT   # 到等待点立刻放，并 SendMessage 通知下一位
python3 tools/gamelock.py status
```

- ⚠️ **共享账号是单玩家**：服务端只有一份"当前所在公司"指针。别人 `visit` 会把玩家从你的节点里拽走。
  **离线建设超过 ~15 分钟：先 `leave` 再 `release`**；**接管锁后第一件事是 `poll` 确认 live 节点是不是你的**，不是就别动。
- ⚠️ **token 只有一份**：任何一方 `login` 会把另一方踢下线。**只有持锁者有权 login**；非持锁者见"请先登录"就去排队，别登录。
- `tools/ts.py` 的写操作（`visit/advance/choose/say/meet/leave`）强制校验锁；`status/poll/material` 只读免锁。
- **持锁只做必须在线的事**（说话、约见、提交、判定轮询）；写代码/写文档/部署一律离线做。
- **等锁不空等**：去备交付物、拆判定依据 checklist、写场景裁决表、起草答案（`docs/RULES.md §12.4`）。
