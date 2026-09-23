# Tech Summit 2026 平台 API（逆向自 SPA bundle）

来源：`https://d25uq4rhmmcney.cloudfront.net/assets/index-DZr2-DhA.js`

## 传输约定

- **所有请求都是 `POST`**，body 为 JSON，即使是读操作。
- Base URL：`https://d25uq4rhmmcney.cloudfront.net/api`
  （bundle 里另有 `https://u1q88lye6j.execute-api.us-west-2.amazonaws.com`，走 CloudFront 即可）
- 必需 headers：
  ```
  Content-Type: application/json
  Authorization: Bearer 811f5520bb0d735efa1d980a21fea77f30dd7277721c2d63   # 静态应用密钥，非会话
  x-amz-content-sha256: <sha256(请求 body 的 UTF-8 字节) 的 hex>
  ```
- 会话令牌不在 header，而是**放进 body 的 `token` 字段**（`/auth/*` 除外）。
- HTTP 401 表示会话失效，需重新 `/auth/login`。

## 玩家端点

| 端点 | body | 说明 |
|---|---|---|
| `/auth/login` | `{username, password}` | → `{token, role, display_name, avatar}` |
| `/game/gate` | `{}` | 开局闸门状态（管理员是否已 start） |
| `/game/status` | `{token}` | 全局状态：`hud`、`current`、`expect`、`roles`、`companies`、`affinity` |
| `/game/welcome` | `{token}` / `{check:1}` | 首次欢迎弹窗 |
| `/game/team` | `{name}` | 改队名 |
| `/game/action` | `{theme, npcs?}` | **进店拜访（耗 1 回合）** |
| `/game/play` | `{}` | 推进台词（advance） |
| `/game/play` | `{action:{type:"choice", index}}` | 选项作答 |
| `/game/play` | `{action:{type:"text", text}, file_info?}` | 自由作答 / 提交 URL+TOKEN |
| `/game/play` | `{action:{type:"meet", npcs:[...]}}` | 约见选人 |
| `/game/poll` | `{token}` | 轮询（评审中 / 重读当前场景，**只读，不推进**） |
| `/game/material` | `{key}` | 取材料下载签名 URL |
| `/game/leave` | `{token}` | 返回会场（**不耗回合**，进度保存） |
| `/upload` | `{filename}` | → `{upload_url, key}`，然后 `PUT` 文件到 `upload_url`，再把 `{key,name,size}` 作为 `file_info` 传给 `/game/play` |
| `/leaderboard/api` | `{}` / `{top:1000}` | 排行榜 |
| `/myhistory/api` | `{days, theme?}` | 我的对话记录 |
| `/game/reset` | `{token}` | 重开一局（**危险，会清空进度**） |

## 响应结构

```jsonc
{
  "acts": [                         // 要连播的剧情片段
    {"act":"scene",  "bg":"...", "bgm":"..."},
    {"act":"sprite", ...},
    {"act":"say",    "speaker":"lin", "text":"...", "replay":true},
    {"act":"prompt", "text":"...", "options":[...]},   // options 存在即为选择题
    {"act":"feedback","score":8, "text":"评语", "evidence":"s3key"},
    {"act":"meet",   "candidates":[...]},
    {"act":"gate"|"notice"|"end"|"visit_end", ...}
  ],
  "expect": "text" | "meet" | "judging" | null,
  "pending": {
    "kind":"talk", "node":"t_lin", "speaker":"lin",
    "round":0, "max_rounds":20,
    "upload":false, "upload_kind":"video", "upload_hint":"",
    "history":[{"kind":"npc"|"me"|"fb"|"sys"|"doc"|"evidence"|"alert"|"audit", "text":"..."}]
  },
  "current": "quest_melive_v11",
  "hud": {
    "turn":4, "turns_total":150, "passed":0, "total_score":319,
    "affinity":{...}, "rel":{},
    "themes":[{"id","name","state","score","npcs","playable","reason","industry"}],
    "flow": {"score":0, "goal":{...}, "affinity":{...}},   // 当前关卡内状态
    "done": false
  }
}
```

`act` 取值全集：`scene` `sprite` `say` `prompt` `feedback` `meet` `gate` `notice` `end` `visit_end`
`history.kind` 全集：`npc` `me` `fb` `sys` `doc` `evidence` `alert` `audit` `chat` `prompt`

## 本地工具

- `tools/ts_api.py` — 原始客户端，输出完整 JSON（`login/status/poll/visit/say/choose/meet/advance/leave/board/raw`）
- `tools/ts.py` — 紧凑渲染器，只打印决策需要的信息；每次调用把完整响应存到 `/tmp/ts_last.json`
- 会话 token 存在 `.ts_token`（已 gitignore 意图，勿提交）

```bash
python3 tools/ts_api.py login <user> <pass>
python3 tools/ts.py status
python3 tools/ts.py poll
python3 tools/ts.py visit quest_melive_v11
python3 tools/ts.py sayfile /tmp/answer.txt     # 长回答走文件，避免 shell 转义
python3 tools/ts.py meet lin,zhao
python3 tools/ts.py choose 1
python3 tools/ts.py advance
python3 tools/ts.py leave
```
