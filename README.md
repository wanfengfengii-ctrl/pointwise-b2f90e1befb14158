# 海岬直播字幕供给服务

海岬会展中心的节目运营员登记直播间和供给区间。字幕网关将已切分片段及其整数工作量送入服务，渲染池回报完成，值班员按积压估算核对维护目标。接班员可分别核对实时供给和历史确认。

## 运行

在项目根目录使用 Python 3.11。服务仅用标准库。

```sh
python3 -B -m rooms.http --data-dir ./data --port 8765
python3 -B check_project.py
python3 -B demo.py
```

服务默认绑定 `127.0.0.1`。`--initialize-only` 建库后退出。`--capacity-a` 和 `--capacity-b` 只为缺失配置提供默认值，默认各为 16 槽。应用库为 `service.sqlite3`，池库为 `pool-A.sqlite3` 和 `pool-B.sqlite3`。重跑初始化保留已有配置、房间、任务和切换记录。演示在独立临时目录开场和运行样例，不改变服务数据。

## HTTP 接口

POST 请求体为 JSON 对象。GET 使用表中的查询参数。标识符区分大小写，`pool` 取 `A` 或 `B`，分配对象须恰有 `A`、`B` 两个整数键值。槽位和工作量字段接受整数，布尔值无效。

| 请求 | 参数 | 成功返回 |
| --- | --- | --- |
| `POST /rooms` | `room, floor, ceiling, initial` | `room, floor, ceiling, initial, status`，状态为 `opening` 或 `open` |
| `GET /rooms` | `room` | 登记和当前开场状态 |
| `POST /segments` | `room, segment, work` | `room, segment, work, status, pool` |
| `POST /segments/complete` | `segment, pool` | 原片段的 `completed` 状态及原池 |
| `GET /demand` | `room, cycle_work` | `waiting_work, suggested_slots, cycle_work` |
| `POST /switches` | `room, switch_id, target` | `pending` 或 `completed`，完成时带 `allocation` 和 `receipt` |
| `GET /switches` | `room, switch_id` | 指定请求的状态及原结果 |
| `GET /pools` | `room, pool` | `pool, status, slots`，已确认零额度返回整数 `0` |
| `GET /handover` | `room` | `pools, total, pending, receipts`，实况缺失时对应 `slots` 和 `total` 为 `null` |

```sh
curl -sS -H 'Content-Type: application/json' -d '{"room":"main","floor":6,"ceiling":10,"initial":{"A":8,"B":0}}' http://127.0.0.1:8765/rooms
curl -sS -H 'Content-Type: application/json' -d '{"room":"main","segment":"intro","work":4}' http://127.0.0.1:8765/segments
curl -sS 'http://127.0.0.1:8765/demand?room=main&cycle_work=4'
curl -sS -H 'Content-Type: application/json' -d '{"room":"main","switch_id":"S1","target":{"A":0,"B":8}}' http://127.0.0.1:8765/switches
curl -sS 'http://127.0.0.1:8765/handover?room=main'
```

无效输入为 400，资源不存在为 404，同号异参、未开场、错池或在办冲突为 409。开场或切换 POST 尚未完成时返回 202，可原号原参重试。池暂不可确认时单池查询返回 503 及 `unconfirmed`，交班仍可读到持久在办和历史回执。

## 业务规则

开场先校验整数区间、初始合计和池能力，再登记待开场。两池分别提交，读回等于原登记后才开放。开场同参重试接续原登记。各池能力约束其已存总承诺，受理时也计入其他在办操作已承诺的目标。

片段号全局唯一，绑定直播间及正整数工作量。片段按持久入队顺序分派，池按 A、B 顺序检查。每个已接纳片段占一槽。降额后的在途任务继续在原池处理，新任务等实际余量。原池完成只释放一次，随后尝试分派队首。

每个周期中单槽能处理 `cycle_work` 个工作单位。等待片段工作量之和为 `W`，所需槽位按 `(W + cycle_work - 1) // cycle_work` 向上取整并限制在公布区间。空队列建议保底。估算只读，维护目标由调用方提交。

一场同时办理一次切换。维护期间每笔池端提交后的总槽位都在房间区间内。失答保留原请求，按原参数重试可接着办理。只有两池实际到达目标、旧调额无法再改额后才签回执。完成后，同号同参返回原结果，后续反向切换只改变当前实况。
