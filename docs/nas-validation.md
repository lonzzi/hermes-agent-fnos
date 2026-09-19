# 2026.9.14.2–2026.9.14.3 飞牛实机验证

日期：2026-09-19。平台：ARM64 fnOS，Linux 6.18.18.c1090-trim，appcenter-cli 1.0.1。

## 根因与修复

旧包在 `install_callback` 才生成 dashboard.env，但飞牛在调用该回调之前会解析 Docker Compose，因此报 env file not found。将初始化移到 `install_init` 后，实际设备又暴露出包用户无权创建尚不存在的 @appconf / @appdata 应用目录。

修复为 install_init 提前创建凭据与数据目录，生命周期脚本使用 root 权限完成这些准备工作及 Docker 状态检查。容器保留上游 s6 启动逻辑，Hermes 服务使用 UID/GID 10000。未挂载宿主 Docker socket。

## 已通过

- 在未安装该应用的 ARM64 NAS 上，由 appcenter-cli 安装 2026.9.14.2。
- 飞牛应用列表版本为 2026.9.14.2，状态 start；Docker 状态 running healthy。
- 未登录访问受保护接口返回 401。
- 错误密码返回 401；正确密码登录后会话接口返回 200。
- 从客户端访问 NAS 的 19119 端口成功。
- 飞牛 stop 后容器 exited、应用 stopped。
- 飞牛 start 后控制台恢复健康，原密码仍可登录。
- Hermes CLI 报告 v0.21.3 (2026.9.14)，upstream 345cd2b0。
- 通过应用中心从 2026.9.14.2 原地更新到 2026.9.14.3，更新完成后应用和容器恢复运行，容器健康检查通过。
- 更新前后 `dashboard.env`、`config.yaml` 和 `auth.json` 的 SHA-256 一致，现有控制台凭据、Hermes 配置和认证信息未被改写。更新前另建立并校验了完整离线备份。
- Hermes 图标出现在 fnOS 桌面；点击“打开”后在桌面内生成 iframe 窗口，没有创建新的浏览器标签。

## 尚未验证

- 完整 Agent 模型调用：未使用用户模型额度执行测试。
- 卸载保留数据、最低系统版本、其他设备架构。

临时验证数据已清理，应用保留运行。凭据不进入仓库或测试记录。
