# 公司认领表 · Tech Summit 2026

**⚠️ 现在有两个并发会话在玩同一账号 `u031003`**（共享 150 次拜访预算）：
- `Kestrel-7` —— 会话 `automation-workshop-ea`，负责 **ME Live**（`quest_melive_v11`）到签约。
- `Petrel-9` —— 本会话，负责 **星云智能**（`quest_xingyun`）。

**本 Agent 代号：`Petrel-9`**（全程不变。注：两个会话都从仓库里继承了 `Kestrel-7` 这个代号，
已约定：先到的 ME Live 会话保留 `Kestrel-7`，本会话改用 `Petrel-9`。）

**并发纪律**：同一时刻只有一个会话调用 `/game/action` / `/game/play`；拿到"操作太快，另一处请求正在处理"
时**一律先 `poll` 读真实状态，绝不重发**（见 RULES §H7）。不碰对方认领的公司。

规则见 `RULES.md` §H4：开工前 assign 自己 → 止损/完成后 unassign → 只挑未被 assign 的公司。

| theme | 公司 | 行业 | state | score | assignee | 起 / 止 | 备注 |
|---|---|---|---|---|---|---|---|
| `quest_melive_v11` | ME Live | 泛娱乐/出海社交 | 1 洽谈中 | **315** | **Kestrel-7** | 2026-09-23 起 | `t_lin` 90 · `t_zhao` 45 · `t_wu` 90 · `t_inc` 90；停在 meet 节点 `m5` |
| `quest_xingyun` | 星云智能 | 智能制造/智能家居出海 | 1 洽谈中 | 319 | **Petrel-9** | 2026-09-23 起 | 已有 319 分，当前"未签约最高分"，签下即全额落袋 |
| `quest_verikon` | 维立康制药 | HCLS 跨国药企 | 0 | 0 | — | — | 满分 1000，含 2 道 `cde_rest` + PDF + 录屏，成本最高 |
| `quest_genex_mig` | 创世中本聪 | 数字资产交易所/跨云迁移 | 0 | 0 | — | — | 含在线门控服务 + 录屏 + 文档 |
| `quest_junchi_svc` | 骏驰汽车 | 汽车出海售后 | 0 | 0 | — | — | 4 份交付物：纪要→方案→录屏→REST |
| `quest_shoresell` | 销智云 CRM | ISV·SaaS CRM | 0 | 0 | — | — | CTO 对平台锁定极敏感（-10） |
| `quest_xingchen_fsi` | 星辰证券 | FSI 出海券商 | 0 | 0 | — | — | 合规总监一票否决；部分人需引荐 |
| `quest_chaoxi` | 潮汐游戏 | 游戏 | 0 | 0 | — | — | 业务线吵不拢先做哪条 AI |
| `quest_tuyue_ota` | 途悦旅行 | OTA | 0 | 0 | — | — | 多云架构，筹备上市 |
| `quest_hcompany` | PearlMedia HK | Telecom/Media Pay-TV | 0 | 0 | — | — | 英文剧本 |

## 认领历史

- 2026-09-23 `Kestrel-7` assign → `quest_melive_v11`（承接已开局的洽谈）
- 2026-09-23 12:50 `Petrel-9` assign → `quest_xingyun`（与 `Kestrel-7` 协商分工，避免同节点重复烧回合）
