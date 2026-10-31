# 更新记录

## 0.4.1-public — 2026-10-31

- 配管正式写入前先完成走廊、标高、阀组和操作检修空间规划，禁止边接边绕。
- 至少比较两个有实际差异的候选；只有一个可行时记录排除原因。先判硬约束，再比较长度、弯头、升降和支撑条件。
- 新增紧凑规划表、真实外包络检查、变更重规划及资料来源说明；不新增逐段用户审批。
- 本次仅修改skill说明和打包版本，不改桥接执行逻辑或现场模型；署名保持adrcyf。

## 0.4.0-public — 2026-10-30

- 整理三个skill、桥接源码、自编译适配器及离线测试，去除本机账号路径和工程实例数据。
- 保留PDMS每批清屏、自然日志会话管理及按需只读打开CAD的工作规则。
- 增加Sol主代理、Terra执行子代理的可选分工说明，明确单PDMS会话串行执行和接口验收。
- 保留作者署名及非执行来源标记；不包含核验密钥、图纸、模型、凭据或运行数据。

## Attribution update — 2026-10-30

- Public author and maintainer attribution uses the handle adrcyf.
- Public commit metadata and package provenance use the same handle.
