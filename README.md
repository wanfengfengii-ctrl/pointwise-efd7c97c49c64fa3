# 口述史馆导览审听服务

采访台登记讲述和译声的确切原件。编辑把它们排入两条轨道并冻结校样。无障碍审听员领取校样的一段，签发员核齐新版的可听拍后交付。馆员据成品号领取原播放清单、素材出处和逐拍审听依据。

## 运行

使用 Python 3.11 标准库，单个 SQLite 数据库服务一条导览。服务只监听本机。播放清单指向原件及源内拍，音频混流由馆方播放端负责。

```sh
python3 -B -m release.service init --db guide.sqlite3
python3 -B -m release.service serve --db guide.sqlite3 --port 8080
python3 -B check_project.py
python3 -B -m examples.demo
```

平台物化时提供 `check_project.py`。完整套件从 `tests` 发现测试。初始化和启动都会补齐空父版 `root` 及缺失的 `examples/recordings.json` 原件。重复执行保留已有原件、修订、领单、回执和成品。演示用临时数据库和本机 HTTP 运行 `examples/day.json`，最后重开同一数据库领取原成品。测试和演示均可在没有互联网连接时运行。

## 接口

请求与响应使用 UTF-8 JSON。POST 传对象。客户端提供的标识以 ASCII 字母或数字开头，最长 64 字符，其余字符可用 ASCII 字母、数字、点、下划线和连字符。原声修订是字符串。以下路径中的花括号表示路径参数。

| 方法及路径 | 输入 | 成功结果 |
| --- | --- | --- |
| POST `/intake` | `recording`, `revision`, `length`, `origin` | 原件、长度、出处和 `available` 源窗 |
| GET `/intake/{recording}/{revision}` | 原件的确切标识 | 同一固定原件 |
| POST `/edit_version` | `version`, `parent`, `operations` | `version`, `parent`, `length`, `tracks`, `preview_id` |
| GET `/preview_version/{version}` | 可选成对查询参数 `start` 和 `end` | 固定版的 `window`, `beats`, `spans`, `tracks`, `preview_id` 和 `version` |
| POST `/review_order` | `order_id`, `version`, `window` | 固定单号、版、窗口、试播标识及 `playlist` |
| POST `/review_decision` | `request_id`, `order_id`, `decision` | 固定回交请求、原单和结论 |
| GET `/coverage/{version}` | 目标版号 | `version`, `pending`, `evidence` |
| POST `/issue` | `request_id`, `version` | `status: issued`、成功 `receipt` 和固定 `artifact` |
| GET `/read_release/{release_id}` | 成品号 | 原样签存的 `artifact` |

`origin` 为非空出处文字。`length` 是正整数，可用源窗为 `[0,length)`。窗口在 JSON 中写成 `[start,end]`，表示左闭右开，端点为非负整数。两条轨道依次为 `narration`、`translation`。

编辑操作在指定父版的工作副本上顺序执行。每次出现有一个在该版内唯一的编辑用 `slot`。试播还公开稳定的 `occurrence_id`，该身份跨移动和裁切保留。移除后重用旧槽名属于新摆放。操作字段如下。

| `op` | 其余字段 | 行为 |
| --- | --- | --- |
| `place` | `slot`, `track`, `recording`, `revision`, `source`, `at` | 在 `at` 放入原件的 `source` 源窗 |
| `move` | `slot`, `at` | 在原轨移动，源窗和出现身份保留 |
| `trim` | `slot`, `source` | 保留当前源窗的非空子窗，保留拍在版内的位置保持原样 |
| `copy` | `slot`, `as`, `at` | 在原轨创建新出现，`as` 是目标槽名 |
| `remove` | `slot` | 移除该出现 |

所有编辑结束后一次检查布局。同轨允许首尾相接。两轨同拍有声时，两份贡献均按固定轨序返回。父版和原件保持可读。版长为最远摆放终点，空校样版长为零。逐拍贡献给出轨道、槽名、出现身份、原声修订、源内拍和出处。`spans` 按 `silence`、`solo`、`mix` 归并相邻同类拍。全版试播可以为空，显式试播窗和审听窗须在版界内且至少一拍。

回交结论可用 `approve` 或 `return`。同号同参复领，异参返回冲突。回交始终指向原领单。每个目标可听拍在一笔核准的原窗口内找到同一原拍且完整组合一致时才覆盖。组合比较使用原出现、原声修订和源内拍。多笔有效时按回执号字典序再按原拍选择。证据含 `target_beat`、`receipt_id`、`order_id`、`review_version`、`review_window` 和 `review_beat`。成品证据另携 `sources` 原件定位。空白拍不需要审听，空白或已经覆盖的拍会截断待审区间。

签发未覆盖的版返回 HTTP 409，正文含 `status: pending`、`version` 和 `pending`，补听后可用同号续办。成功后，同号同版返回同一成品和首执，同号换版返回冲突。试播、领单和签发均按指定冻结版工作。后来的修订或审听依据不会改写历史成品。

其他业务错误以 `error` 和 `message` 返回。非法输入、拍窗和布局返回 400，未知路由或原件、版、单、成品返回 404，标识冲突返回 409，SQLite 在处理请求时失败返回 500。失败的写入整体回滚。

## 一天的样例

1. 采访台登记 6 拍的 A 和 4 拍的 B，编辑按确切修订引用。
2. 编辑把 A 的源窗 `[2,6)` 摆到 `[0,4)`，B 的 `[1,3)` 摆到 `[1,3)`，另把 B 的 `[3,4)` 摆到 `[5,6)`，冻结 R1。
3. R1 的 `[1,3)` 是叠声，`[4,5)` 是空白。在版内拍 1，A 与 B 对应源内拍 3 和 1。
4. 审听员领取 R1 的 `[1,3)`，听后回交核准。签发员看到 `[0,1)`、`[3,4)`、`[5,6)` 待审。
5. 编辑只保留共同听过的 A、B 部分，整组移到 `[6,8)`，另在 `[8,10)` 复制一组，冻结 R2。
6. 签发员确认移位组沿用 R1，复制组仍待审。第一次提交签发无成品。
7. 审听员补听复制组。签发员以原请求号续办，固定原单和补听单两组证据。
8. 馆员按成品号领取，重开后同号仍返回原清单和依据。
