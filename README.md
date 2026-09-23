# Tech Summit 2026 · CDE Enable Platform — Agent 自动推进

用 Claude Code 作为 AWS 解决方案架构师（SA）自动推进 Tech Summit 2026 的 CDE 实战考核：
走进园区里的客户公司，与 NPC 决策人洽谈、守住合规边界、通过文档 / 录屏 / REST 服务验收、拿下签约。

## 目录

| 路径 | 内容 |
|---|---|
| `docs/RULES.md` | 面向 AI 的完整规则手册（计分口径、红线清单、对话模板、战术启发） |
| `docs/API.md` | 平台 API 契约（逆向自前端 bundle） |
| `docs/ASSIGNMENTS.md` | 十家公司认领表（多 Agent 协作用） |
| `docs/PROGRESS.md` | 进度日志，每次交互更新 |
| `tools/ts_api.py` | 原始 API 客户端 |
| `tools/ts.py` | 紧凑渲染器 / 游戏驱动 |
| `.claude/skills/tech-summit-player/` | Claude Code skill |

## 用法

```bash
python3 tools/ts_api.py login <user> <pass>   # 会话 token 写入 .ts_token（不入库）
python3 tools/ts.py status                    # 全局：拜访次数 / 总分 / 各家进度
python3 tools/ts.py poll                      # 只读当前场景
python3 tools/ts.py sayfile /tmp/answer.txt   # 自由作答
python3 tools/ts.py leave                     # 返回会场（不耗拜访次数）
```

## 关键口径

- **拜访次数**（`hud.turn`，150 次）是唯一硬预算；**一次拜访内的对话轮次不消耗它**。
- `总分 = Σ(已签约客户得分) + max(未签约客户得分)` —— 签约才全额落袋。
- 越界扣分且信任永久回退，比"答得不够好"贵得多。

> 凭据不入库：账号口令仅在本地使用；`.ts_token` 已 gitignore。
