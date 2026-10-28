# Home Assistant 与 HAOS 研究底稿

日期：2026-10-27（美东）。这份底稿把 Home Assistant、它的生态和 HAOS 记下来，供接下来对照我们自己的 Hub 找差距。这里不选定方案。解决方案等研究之后再写。

相关材料仍在对话旁的两份画布里，不在本仓库：

- [加拿大进入策略](https://cursor.com/canvas/store-49bf722b-1b16-4c5d-ae1d-965985e4e3fd/aa6f27eb-8443-4380-80aa-0d055bd3b431)
- [Hub 与 Home Assistant Green 对比](https://cursor.com/canvas/store-49bf722b-1b16-4c5d-ae1d-965985e4e3fd/268126f2-8f55-40f7-b986-695350a08e7c)

## Home Assistant 是什么

Home Assistant 是一套装在自己家里的家居自动化系统。灯、门锁、传感器、摄像头的状态和自动化都留在本地这台主机上。手机、浏览器面板和语音助手连到这台主机，不自己再保存一套家。

本地控制不需要订阅。Nabu Casa 的 **Home Assistant Link**（以前叫 Home Assistant Cloud）是可选项：每月 6.50 美元，或每年 65 美元。它提供外网访问、异地备份、Alexa / Google Home 接入，以及云端语音识别和合成。我们的产品原则仍然是远程只走 Tailscale / WireGuard，不把开锁交给 Alexa 或公网端口转发。见仓库根目录 `README.md`。

核心是一个状态机。每个设备是一个实体。状态变化进入事件总线。自动化监听这些事件，例如「门口有人，廊灯打开，锁保持锁上」。

## 四个名字

| 名字 | 是什么 |
| --- | --- |
| Home Assistant Core | Python 写的家居程序。所有安装方式里都有它 |
| Supervisor | 管理 Core、应用、备份和系统更新的容器 |
| 应用（以前叫 add-on） | 跑在旁边的独立程序，例如 MQTT、ESPHome、Zigbee2MQTT、Frigate |
| HAOS | 用 Buildroot 做的 Linux，只负责把上面三样跑起来 |

应用商店只在 HAOS 里有。用 Docker 单独跑 Core（官方叫 Container 安装）时，MQTT 或 Frigate 要自己另起容器。

## 2026 年还被支持的装法

2025 年 5 月 22 日，官方宣布弃用两种装法，并从 Home Assistant 2025.6 起提示，大约到 2025.12 结束支持：

- 在 Python 虚拟环境里直接跑 Core
- 在 Debian 上装 Supervised

之后正式推荐的是：

- **HAOS**：给大多数人。系统更新、应用商店、备份都由 Supervisor 管。
- **Container**：给已经自己管 Docker 的人。只有 Core，没有 Supervisor，也没有应用商店。

Green 出厂就是 HAOS。

## HAOS 里面有什么

HAOS 不是 Debian 或 Ubuntu，也不能把它当成普通 Linux 随便 `apt install`。官方说明写明它用 Buildroot 从源码编出来，一块板子一份镜像。

和我们以后做成品盒子相关的几点：

- 根文件系统是压缩的、只读的 EROFS。
- 更新用 RAUC，系统有 A/B 两个槽。新槽起不来就回到旧槽。
- 启动后由 systemd 管网络（NetworkManager）、时间和蓝牙（BlueZ）。
- Docker 里跑 Supervisor。Supervisor 再启动 Core、DNS、mDNS、音频，以及用户装的应用。
- 新镜像第一次开机才下载当前版本的 Core。配置、自动化和数据库在数据分区，刷系统不把「这个家」清掉。
- 应用之间和 Core 的通信走 Supervisor 提供的 DNS。部分应用仍沿用旧目录名 `addons`。

官方镜像按板子单独做。Green 是其中一台整机，芯片是 RK3566。ROCK 5T 不在官方整机名单里。社区镜像即使能启动 HAOS，也不等于 RK3588 的 NPU 和厂家内核能进官方 HAOS。这一点在和 Green 的对比里已经写过：Frigate 要使用 Rockchip NPU，通常需要厂家内核，而 HAOS 用的是自己的内核和只读根文件系统。

## 生态

**集成**写在 Core 里，负责听懂某一类设备。常见的有 Zigbee 的 ZHA、Z-Wave JS、Matter、MQTT、HomeKit、各品牌摄像头和云账号。

**无线电台**是另一件硬件。Connect ZBT-2 是官方 USB 电台，建议零售价 49 美元，一根专做 Zigbee 或 Thread 其中一种。Z-Wave 是另一根 Connect ZWA-2。Green 主板没有电台，要外接。

**ESPHome** 给 ESP32 一类芯片写固件，设备直接向 Home Assistant 报告状态。它和 Home Assistant 同属 Open Home Foundation。

**HACS** 是社区商店，安装官方仓库以外的集成和面板卡片。Frigate 的界面可以走 HACS，也可以在 HAOS 里装成应用。应用是录像进程，集成是把检测结果放进 Home Assistant 的状态机。两个都要有，摄像头才会出现在自动化里。

**蓝图**是写好的自动化模板。导入后填上自己的实体就能用。

**语音**可以全部留在本地：Assist、Whisper、Piper 和唤醒词。Link 订阅则把识别和合成交给 Nabu Casa。

组织上，Open Home Foundation 持有 Home Assistant 和 ESPHome。Nabu Casa 做官方硬件和 Link，并把大部分利润交给基金会。官方硬件包括 Green、Yellow、Connect ZBT-2 和 ZWA-2。Green 的建议零售价在 2026 年 4 月调到 199 美元 / 179 欧元。加拿大本地库存此前见过约 349 加元。

## 和我们 Hub 的对应

我们的仓库是一套自己的 Python 进程，不是 HAOS，也进不了 Home Assistant 应用商店。`python -m hub` 拉起 FastAPI、门口视觉、车道摄像头、对讲、锁和灯。远程是 Tailscale，见 `README.md` 和 `docs/setup.md`。

| Home Assistant 里的概念 | 我们现在的位置 |
| --- | --- |
| Core 状态机和事件总线 | `hub/state.py`、`hub/notify.py` 的 `EventBus`、`hub/storage` 里的事件表 |
| 自动化 | `hub/ai/rules.py`，加上门口连续帧确认、布防后的声光（`hub/elegoo_alert.py`） |
| 集成 / 设备适配器 | 锁 `hub/devices/lock.py` 与 `zwave_lock.py`，灯 `zigbee_light.py`，门铃 ONVIF `doorbell.py`，车道 `driveway.py` |
| 面板和手机 | 自研 Android（`android/`）和 iOS（`ios-app/`），不是 Home Assistant Companion |
| 录像和检测 | `hub/vision/people.py` 的 YOLOv8n。报警标签默认只有人。没有 Frigate，没有 24/7 录像（`docs/plan-recording-search.md` 第 3 步还在等 NVMe） |
| 语言模型 | `hub/ai/rkllm_bridge.py`，默认 Qwen2.5 0.5B 的 RKLLM 文件 |
| Zigbee | CH340 协调器，`HUB_ZIGBEE_DEVICE`。空字符串表示不启用 |
| Z-Wave | Zooz 棒，`HUB_ZWAVE_DEVICE`。空字符串表示锁还是内存桩 |
| 远程 | TLS + Tailscale / WireGuard。没有 Link，没有公网中继 |
| 系统更新和备份 | 没有 RAUC，没有 Supervisor 备份。实验室机是 Windows venv，产品目标机是 ROCK 5T |
| 应用商店 | 没有。功能都在同一个进程里 |

YOLOv8n 和 Frigate 的 YOLO-NAS M 都是 COCO 检测模型。YOLO-NAS M 在公开数据集上更准，但换模型不会带来 Home Assistant 的状态机、应用商店或多路录像。门口场景下，我们继续用已经接好的 YOLOv8n。

## 研究时要回答的差距

每一条都先写「Home Assistant 怎么做」和「我们哪段代码在做同一件事」。先不要改产品。

1. **实体模型。** Home Assistant 用统一的实体和事件总线把灯、锁、人、门铃接进同一条自动化。我们的事件类型是分散的（门口的人、车道、门铃按钮、开锁）。差在哪里才值得做成统一模型，而不是继续用现在的 HTTP API（`docs/v1-api.md`）？
2. **自动化谁来写。** 用户今天改不了规则，规则在代码里。Home Assistant 让用户在界面里改触发条件。我们的安防产品要不要把「布防时有人则报警」开放成用户可改的规则，还是保持写死，避免误关报警？
3. **设备覆盖。** ZHA、Matter、ESPHome 能接的设备远多于我们现在的一只灯和一把锁。第一批必须自己接的设备是哪些？哪些明确不接、留给以后？
4. **电台。** ZBT-2 一根只做 Zigbee 或 Thread。我们的 CH340 棒和 Zooz 棒是两条线。成品盒子上电台怎么固定、怎么在拔插后恢复，已经有 Zigbee 重连（`hub/devices/zigbee_light.py` 相关修复）。Thread / Matter 要不要出现在第一台成品里？
5. **录像。** Frigate 在 HAOS 里是一个应用：运动裁剪、跟踪、分区、硬盘录像。我们是单进程上的 YOLOv8n，24/7 录像还没做。差距是「缺少一个 NVR」，还是「门口事件已经够用，NVR 会拖垮 NPU」？Qwen 0.5B 和检测共用 NPU，这是我们的约束，不是 Home Assistant 的约束。
6. **系统形态。** HAOS 给了只读根文件系统、A/B 更新和应用隔离。我们若继续一个 Python 进程，更新和回滚靠什么？若改跑 HAOS，RK3588 的 NPU 检测和 RKLLM 放在哪里？这条在动手前要有实验记录，不能只靠文档推断。
7. **远程和账号。** Link 用订阅换外网和语音云。我们用 Tailscale。要确认的是：没有订阅时，手机离开家以后对讲和开锁还在不在，以及用户要不要自己装 Tailscale。
8. **面板。** Companion 和 Lovelace 能配几乎所有实体。我们的手机和室内机只做门口、对讲、开锁、布防。少掉的是通用家居面板，还是安防流程被通用面板淹没？产品意图写的是门厅电脑，不是又一台 Green。

## 事实来源

- HAOS 构成与启动：<https://contributors.home-assistant.io/os/operating-system/>
- 应用（原 add-on）只在 HAOS：<https://www.home-assistant.io/apps/>
- Supervisor 的职责：<https://developers.home-assistant.io/docs/supervisor/>
- 弃用 Core 与 Supervised 安装：<https://www.home-assistant.io/blog/2025/05/22/deprecating-core-and-supervised-installation-methods-and-32-bit-systems/>
- Green 规格与 2026 年 4 月价格：<https://www.home-assistant.io/green/>，<https://www.nabucasa.com/news/2026-01-08-green-pricing-change/>
- Connect ZBT-2：<https://www.home-assistant.io/connect/zbt-2/>
- Link 价格：<https://www.nabucasa.com/link/>

价格和弃用时间以这些页面当时的文字为准。各省电气和消防要求不在这份底稿里。
