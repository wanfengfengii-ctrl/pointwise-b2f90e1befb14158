# 主会场字幕切换核对

主会场以 `(8,0)` 开场，申请把已生效额度迁往 `(0,8)`。括号内分别是 A、B 的槽数。保底为 6，上限为 10。正常回归、样例和业务 HTTP 接口见 README.md。

- `python3 -B incident.py band` 通过 HTTP 开场并完成切换，逐笔检查两个池实际提交后的额度。
- `python3 -B incident.py before` 和 `python3 -B incident.py after` 分别在首次调额提交前和提交后模拟回包丢失，核对待办后重开服务，以原请求号和参数继续。首次调额由服务选择。完成后将夹具保留的原指令送回原池，读取池库的实生效额度，并复领原回执。
- `python3 -B incident.py all` 运行全部三个对照。每案建立自己的场次和数据库，输出提交轨迹和回执前后的实况。观察到总额越界时输出 `SLOT_BAND_BREACH`，晚到的旧令改额时输出 `STALE_QUOTA_REAPPLIED`。

池端可能在协调服务重开后直接收到此前已发出的调额指令。最终应实际读到 A 为 0、B 为 8，旧令重投后保持原值。现场核对以池端落定的槽数为准，HTTP 回执用于核对原请求的确认结果。

`.pointwise-runtime.json` 的 `start` 启动原业务 API，`GET /healthz` 用于检查进程可接收请求。`verify` 沿用完整原回归，`demo` 走 README.md 的字幕业务样例。
