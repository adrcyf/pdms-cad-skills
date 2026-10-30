# CAD 原生读取与建模依据

工作会话内复用CAD工作进程、原生COM通道及图纸缓存；软件退出时一起释放，不为每次读取重新建立整套通道。CLI为备用路径。

## 优先读取打开的图纸

用户通常会打开 CAD。先用 MCP cad_active_read(action=status) 核对当前文档完整路径，再传 expected_path 限定读取目标，按 types/handles/text_contains 筛选。不激活窗口、不选屏幕点、不发送键盘或把命令粘到控制台。接口通过原生 COM 属性直接取得图元与标注，通常比控制台输入更少交互。本机 ProgID 是 AutoCAD.Application.25，不是 .25.0；优先读取注册表 CurVer。只读查询本身未运行时返回未连接；本使用者已授权按需启动，可先运行scripts/ensure-cad-open.ps1 -Path <完整路径>，以原生COM隐藏启动并只读打开，随后传expected_path读取。无需Activate切图，不发送鼠标键盘。其他使用者未授权或明确禁止启动时遵循其约束。

cad_active_read(action=query) 支持 LINE、CIRCLE、ARC、DIMENSION、TEXT/MTEXT、LWPOLYLINE、INSERT。用 HandleToObject 直取指定对象；类型过滤使用临时非交互 SelectionSet，读取后删除该集合，不改变 Pickfirst、不 Highlight、不 Explode。标注 Measurement、TextOverride、LinearScaleFactor 分开返回；角度单位和图纸缩放仍需核实。实时接口暂不展开嵌套块；INSERT 提供插入点、旋转和缩放，不能把块定义局部坐标当世界坐标。

COM角度标注保留原生弧度值并提供 measurement_degrees；文件读取器的角度测量为度，两通道不可直接把数值互比。界面忙碌时返回未就绪，不通过激活/按键抢占。Handle直取已实测读取47A9圆与20A4标注约0.8秒（含Python到COM入口开销），类型过滤45个标注约3.7秒；这些是本机样本，不是所有电脑性能保证。

CLI：运行本 skill 下 scripts/cad_active.py status 或 query --types DIMENSION --limit 20。Python 入口用标准库调用 Windows 原生 COM，无须 pywin32。每次只读需要的区域/类型/Handle，不全图反复打印。

## 已保存文件备用读取

没有可接入的打开会话时，用 cad_summary/cad_query/cad_preview 处理已保存 DWG/DXF。DWG 由已安装 AutoCAD 的 accoreconsole.exe 在隐藏后台对读取副本导出 DXF；原图不保存、不更改。Python ezdxf 读取坐标、曲线、块变换、属性、文字及标注。缓存按原文件哈希复用，不每次重新导出。不会包含编辑器中尚未保存的修改；不能拿旧缓存冒充实时数据。

cad_query 支持类型、图层、Handle、文字与 WCS XY bbox，limit 最大200并分页；指定布局。LWPOLYLINE 包括弧段 bulge，不能仅按弦长累计；圆/弧的 OCS 需转 WCS；块旋转缩放需应用后再量；DIMENSION 分开保留几何测量、存储测量、覆写文字和有效标注样式。未知/代理/外部参照不能假定读取完整，按 warnings 和图元类型补核。

cad_preview 是不操作界面的离线图像，辅助识别视图和接口；字体、代理对象可能不同于原生显示，尺寸从图元读取。用户允许只截图辅助观察，不等于允许激活、缩放、旋转、点选或切换窗口。需要原生截图时遵循可用 screenshot/computer-use 工具，只采集，不输入；隐藏/最小化无法截取时用现成图片或离线预览并说明。

备用文件读取需要 Python 的 ezdxf（本机1.4.5）；预览另需 matplotlib。直接 COM 读取不需要这两项。另一台机器缺依赖时先检测并明确补齐范围，不宣称仅复制 skill 就能跨所有版本运行。

## 实测与边界

原环境AutoCAD 2025已测试打开图纸的COM读取，以及保存DWG读取副本经Core Console导出DXF后解析。图元实测和覆写标注须分别保留；源图不保存、不修改。仅验证数据链路，不表示所有设备已自动完成。项目图纸、Handle、测量值、哈希及私有联调证据不随公开仓库分发。

## 从数据到模型

依据提供方的CAD、图片和工艺资料工作，记录版本、文件哈希、图元Handle、视向与坐标变换。仅图片时没有可提取的CAD实体，使用图示尺寸及可靠比例，并标注估读；不冒称与CAD实测同精度。记录资料矛盾、缺项与采用依据，不能用“严格照图”掩盖推断或保证原始资料无误。

本使用者当前要求：外形按实际CAD距离复刻、内部可简化，接口位置、朝向、连接面和规格准确。两视图冲突时优先俯视能确定的平面尺寸/位置/周向，立面补标高、倾角和遮挡；俯视不能提供的字段不能凭优先级猜出。优先级被后续明确指示修改时记录覆盖关系。缺少接口/管道/压力等级、内径或壁厚等设计字段，列上报清单；可查到的目录值作为目录候选，不冒充原设计要求。目录层级核对与位置几何核对是不同完成条件。

expected_path现按Documents集合匹配完整路径，可读取非活动的已打开图纸；缺失报错，不悄悄改读其他文档。ensure-cad-open.ps1复用现有应用且不改变其Visible；仅新建实例设Visible=false。不声称AutoCAD本身启动在所有机器绝不显示许可证或初始化提示。

隐藏启动可能出现COM注册延迟：acad进程存在而COM未就绪时停止启动并等待重查，不重复创建实例。
