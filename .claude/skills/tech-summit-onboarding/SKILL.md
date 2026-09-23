---
name: tech-summit-onboarding
description: Onboard a fresh AI onto this project's working mode in one read — what the Tech Summit 2026 CDE game project is, which docs to read in what order, the per-visit work loop, the five rules that cost the most when forgotten, the doc-update duty after every interaction, and the git/--no-verify convention. Use at the start of a new session on this repo, when asked how this project works / how to get started / what the workflow is, or before taking over the game from a previous session.
---

# 上手指南 · Tech Summit 2026 Agent 工作模式

## 一句话

用 Claude Code 扮演 **AWS 解决方案架构师（SA）**，自动推进 Tech Summit 2026 CDE 实战考核：
进 10 家客户公司洽谈 NPC 决策人、守合规红线、过文档/录屏/REST 验收、拿签约。**不是写业务代码的项目。**

平台 `https://d25uq4rhmmcney.cloudfront.net/` · 账号 `u031003` · 队名 `R3C10C` · 本 Agent 代号 **`Kestrel-7`**

## 上手顺序

1. `CLAUDE.md` —— 30 秒总览（每次会话自动加载）
2. `docs/RULES.md` —— 完整规则。**§7.5（要点清单制）、§7.6（守边界=拒绝+替代路）是全文最重要的两节**
3. `docs/intel/<theme>.md` —— 目标客户情报；**顶部一句话就是"下一访方针"**
4. `docs/PROGRESS.md` —— 打到哪了
5. `docs/ASSIGNMENTS.md` —— 10 家公司认领表；开工前用代号 assign 自己
6. `docs/API.md` —— 只在要改工具/调新端点时看

打游戏本身用 `Skill(tech-summit-player)`，规则已压缩在里面。

## 工作循环

```
读 intel → ts.py status → ts.py visit <theme>（耗 1 次拜访）→ ts.py meet 选人
→ 多轮 sayfile 谈透 10 个维度 → 主动收尾触发判定 → poll 取分
→ 写回 intel + PROGRESS → 决定下一访（或 leave 止损）
```

## 五条最贵的规则

1. **拜访次数（150）是唯一硬预算；一次拜访内的对话轮次不消耗它。**
   → 对话要谈全，别省话；要省的是进店次数。
2. **talk 节点是隐藏要点清单制**：分数 = 覆盖要点数 / 总数 × 10。
   实测林工 4/4 = 10 分，老赵 2/4 = 5 分。**谈得漂亮 ≠ 得分，覆盖广度才得分。**
3. **守边界 = 明确拒绝 + 一条同样快的替代路 + 谁做/多久。**
   实测只给抽象合规表、没给场景化替代路 → **0 分 + 好感 −10**。
4. **口径全局一致**：NPC 互相通气会当面对质；所有已承诺口径写进 `docs/intel/`。
5. `leave` 不耗拜访次数，拿不准就撤。**绝不调 `/game/reset`**（清空进度）。

## 每次交互后的硬性义务（用户明确要求）

- 更新 `docs/PROGRESS.md`（分数、好感、发生了什么）
- 更新 `docs/intel/<theme>.md`（新事实、新承诺口径、下一访方针、每人已拜访次数）
- 有新机制发现 → 同时更新 `docs/RULES.md` 与 `.claude/skills/tech-summit-player/SKILL.md`

## Git 约定

仓库 `https://github.com/yagrxu/tech-summit-2026-agent`（public）。
`tools/autopush.sh` 后台每 ~3 分钟自动 commit + push（PID `.autopush.pid`，日志 `.autopush.log`）。
没在跑就重启它：`nohup ./tools/autopush.sh >/dev/null 2>&1 & echo $! > .autopush.pid`

**`git commit` 和 `git push` 都必须带 `--no-verify`** —— 本地 CodeDefender 钩子会拦住推送。
凭据不入库：`.ts_token`、`.env.omni` 已 gitignore，**账号口令不写进任何被跟踪的文件**。

## 命令速查

```bash
python3 tools/ts.py status | poll | leave
python3 tools/ts.py visit <theme>
python3 tools/ts.py meet a,b,c
python3 tools/ts.py sayfile /tmp/a.txt     # 长回答一律走文件，避开 shell 转义
python3 tools/ts.py choose <i>
```
完整响应落 `/tmp/ts_last.json`（看 `pending.of` 候选人等细节）。
`expect=judging` 时每 10 秒 `poll`，复杂验收可能几分钟。
