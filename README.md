# PDMS CAD Skills

原作者及维护者：**adrcyf**。

面向Windows、PDMS 12.1 SP4和AutoCAD的Codex技能套件，通过Python/MCP与原生命令/COM通道读取图纸、辅助设备建模和配管。默认工作流不模拟鼠标键盘、不抢占焦点。

## 内容

| 目录 | 用途 |
|---|---|
| [pdms-bridge](pdms-bridge/SKILL.md) | PDMS命令执行/回传、CAD图元及标注读取、会话与日志管理 |
| [pdms-cad-modeling](pdms-cad-modeling/SKILL.md) | 外轮廓建模、接口位置方向与目录核对、交付核对表 |
| [pdms-piping](pdms-piping/SKILL.md) | PID/端点核对、目录匹配、原生配管命令与回读 |

## 安装

1. 克隆本仓库，将三个同名目录复制到当前用户的`$CODEX_HOME/skills`（通常`%USERPROFILE%/.codex/skills`）。已有同名skill先备份合并，不直接覆盖个人修改。
2. 打开目标PDMS Design，运行`pdms-bridge/pdms.cmd -InspectOnly -NoPause`检查版本和路径。
3. 核对后运行`pdms-bridge/pdms.cmd -NoPause`，部署本仓库自编译适配DLL、备份登记Design自动加载及本机MCP路径。当前已打开的Design首次使用生成的宏加载，或正常保存后重启；以后兼容环境随Design加载。
4. 先检查session/ready，做只读名称、类型和坐标验证。不要在生产设备上随意试改。不同电脑仍需要一次本机准备，复制skill本身不会自动安装插件。

兼容验证起点：PDMS 12.1 SP4 / des.exe 12.1.4.0 / .NET 2 x86。适配器使用版本相关接口，不能保证其他PDMS/E3D版本直接适用。需要当地合法安装的软件及相应目录写入权限。仓库不分发AVEVA/Autodesk厂商DLL或许可证。

Python需3.11+；直接COM读取用标准库及Windows PowerShell，保存DWG/DXF备用解析用ezdxf，离线预览用matplotlib。按需打开CAD使用`ensure-cad-open.ps1 -Path <完整路径>`；先复用已有应用，缺失时隐藏启动、只读打开，不Activate或模拟输入。

## 工作规则

**配管先规划后建模**：先确定走廊、标高和阀组，比较候选路线，检查实体及操作检修空间，形成路线表后才执行建模。详见[配管规划流程](pdms-piping/references/routing-planning.md)。

按源图核对，俯视确定平面位置/周向，立面补标高/倾角；资料冲突记录采用依据。外形允许按任务简化，接口中心、向外方向和连接形式须单独核查。估计值与目录替代明确标记，不冒充设计确认。

每批命令后清屏；自然产生的磁盘日志工作中保留，用户要求或软件退出时按明确清单清理已完成过程文件。保留未知/未决文件及正式交付；不另写永久命令流水账。

可选[Sol主代理＋Terra执行子代理](pdms-bridge/references/agent-workflow.md)：只传必要参数，一个PDMS会话只由一个执行代理发命令。

## 测试与范围

```powershell
cd pdms-bridge/scripts
python -m unittest test_bridge test_lifecycle test_cad_reader
```

以上为离线回归，不操作实时CAD/PDMS。原环境曾验证真实查询、变量执行、临时设备创建清理、错误恢复、清屏与CAD直接读取；不表示所有设备、工程验收或跨版本部署均已完成。

本仓库不包含原始CAD、PDMS数据库、项目模型、运行队列、用户MCP配置、凭据或来源核验私钥。Markdown中的加密来源标记不参与执行、不联网、不跟踪、不限制修改，可删除，仅辅助溯源。

## 分享与修改

允许分享和修改；保留“原作者及维护者：adrcyf”说明，另记修改者和修改范围。项目报告应填写实际编制人，不自动沿用skill作者署名。详见[COPYING](COPYING.md)。
