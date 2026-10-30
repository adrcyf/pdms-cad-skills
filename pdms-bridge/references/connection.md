# 连接、生命周期与验证

## 适配范围

已在Windows、PDMS 12.1 SP4（des.exe 12.1.4.0）、.NET 2 x86环境测试；CAD实时读取使用AutoCAD原生COM。其他版本和第二台电脑须单独验证。源码依赖当地合法安装的AVEVA程序集；本仓库不分发厂商DLL、模型、目录或图纸。

## 一次性准备

将三个skill目录放到当前用户的Codex skills目录。先打开目标Design，运行pdms-bridge/pdms.cmd -InspectOnly -NoPause检查；再运行pdms.cmd -NoPause部署兼容适配器并备份登记DesignAddins.xml中的本桥接项，同时登记本机MCP路径。首次准备需要相应目录写入权限；不调整Windows权限或安全策略。已打开的Design不会热读启动清单，首次需使用生成的加载宏，或由用户保存后正常重启。不能声称复制skill就自动完成本机部署。

使用-ManualOnly选择手动加载，-NoMcp选择CLI。不得覆盖不同哈希的已加载DLL。原厂pdms.bat不修改。

## 连接与执行

先pdms_status核对session、PID、connected、ready及unresolved_requests。每次执行绑定expected_session；按原始资料核对目标，不能用连接成功代替设计验收。Q P1 WRT WORLD明确读取世界坐标。命令失败停止后续行，但不回滚之前写入；超时查询request_id，不重发未知结果的写入。

日志由原生宏HANDLE ANY捕获。ALPHA LOG使用OVER语法，不追加REQUESTS尾参（已测试环境不支持）。$R0减少跟踪；成功和命令错误后先关闭捕获文件，再ALPHA REQUESTS CLEAR及ALPHA COMMANDS CLEAR。已确认归属当前桥接的孤立日志可恢复一次；未知日志不关闭，任意模态弹窗不保证自愈。

## 软件会话

工作中复用MCP、CAD工作进程、COM通道及缓存，不逐命令重启。Design退出或登出后关闭桥接自有辅助进程，不结束用户CAD/PDMS。仅CAD工作时绑定CAD。stdio连接结束后下次会话需要客户端重新连接；不能保证所有客户端自动重连。

磁盘日志是自然收发/捕获文件，不另写命令流水账。工作中保留，用户明确要求或软件退出后清理已完成过程包；先检查明确绝对路径和属性，再逐文件PowerShell Remove-Item -LiteralPath，不Force或递归删除。保留未知、异常、未决及用户交付。重要工程结论放用户要求的核对表，必要临时笔记收尾清理，不默认永久复制全部命令。

## 已测试与限制

原环境已测试查询/中文回传、NOZZLE世界P1、PML变量执行与回读、隔离临时EQUI创建移动清理、普通错误捕获和恢复、成功/错误清屏。离线测试覆盖进程复用及退出清理。CAD实时COM、保存文件读取及CAD几何到临时基本体的数据链路曾通过。以上不是对任意设备、目录、版本的完整自动建模保证。公开仓库不含项目私有测试证据及坐标。

接通新环境后先只读检查名称/类型/世界坐标，确认编码；再在明确授权的隔离对象做最小写入和恢复。用户正常重启后验证自动加载及session更换，不为测试强行关闭用户程序。

## 撤销

由用户正常保存退出Design后，对比备份仅移除DesignAddins.xml中的CJPDMSBridgeV2项，不覆盖其他插件；按明确文件清单清理本适配器。不终止PDMS，不删除数据库。
