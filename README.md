# Hermes Agent for 飞牛 fnOS

将 [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) 封装为飞牛 `.fpk` 应用，提供独立密码登录的 Web 控制台、持久化数据和自动跟进正式版本的 GitHub Release。

社区打包项目，与 Nous Research、飞牛官方无隶属关系。复用上游官方 Docker 镜像，不修改 Hermes 源码；图标来自上游，许可见 `LICENSE-UPSTREAM`。

## 安装

1. 在飞牛中安装并启用 Docker 应用。设备架构支持 x86_64 和 ARM64。
2. 从 [Releases](https://github.com/lonzzi/hermes-agent-fnos/releases) 下载 `hermes-agent-fnos-<版本>-all.fpk`。
3. 应用中心 → 手动安装，选择 FPK，在向导中设置控制台用户名、密码。
4. 从应用图标打开控制台，或访问 `http://NAS地址:19119`，使用刚才的账号登录。
5. 在 Hermes 控制台配置模型提供商 / API Key 和消息渠道，并按需启动 Gateway。空配置不会预先启动 Gateway。

密码须为 12–128 位，可包含字母、数字和 `_.@%+=:!-`；这是本封装对 Compose 配置文件兼容性的约束。

控制台具有运行工具、修改 Agent 配置的能力，请仅对可信网络开放。远程访问使用 HTTPS 反向代理或 VPN。控制台登录凭据独立于飞牛账号。未挂载 Docker socket，也未开放宿主机根目录。

**这是联网安装包**：FPK 包含飞牛配置与脚本，安装 / 更新时由 Docker 下载官方镜像，NAS 必须能访问 Docker Hub。镜像较大，请预留下载时间和存储空间；不是包含所有依赖的离线 FPK。

## 数据与升级

- Hermes 会话、模型配置、技能和工作数据：`${TRIM_PKGVAR}/hermes` → 容器 `/opt/data`。
- 控制台凭据：`${TRIM_PKGETC}/dashboard.env`，文件权限 `0600`。
- 容器名：`hermes-agent-fnos`；默认入口端口：19119。
- `install_init` 在 Compose 校验前创建凭据和数据目录；生命周期脚本使用 root 完成目录准备和 Docker 状态检查，Hermes 服务仍由上游容器内非 root 用户运行。
- 飞牛通过 Docker 项目资源管理启动 / 停止；应用状态要求容器和控制台健康检查均通过。
- FPK 升级脚本不重写登录凭据，不删除应用数据。升级前停止应用并备份上述两个目录；涉及数据库迁移的版本不能保证直接降级，回退需恢复备份。
- 卸载时的数据清理由飞牛处理；请留意卸载选项，不要删除仍需保留的数据。
- SSH 排查：`docker logs --tail 100 hermes-agent-fnos`。
- 可通过 `docker exec -it hermes-agent-fnos hermes setup` 运行官方交互配置。

## 自动发布机制

`Package upstream release` 工作流每 6 小时（UTC 00:23、06:23、12:23、18:23）运行，也可在 Actions 页面手动触发。

1. 查询上游最新正式 GitHub Release，忽略草稿与预发布版本。
2. 检查本仓库对应 `上游tag-fnos.修订号` 是否已发布；已发布则跳过。
3. 解析官方 `nousresearch/hermes-agent:<上游tag>` 镜像，确认支持 Linux amd64 / arm64，锁定多架构索引 SHA256。
4. 使用固定版本、校验摘要的官方 `fnpack 1.2.3` 生成 FPK。
5. 在 GitHub Linux amd64 runner 拉取镜像，验证控制台启动、错误密码拒绝、正确密码登录和会话访问。
6. 检查成功后发布 FPK、`SHA256SUMS` 和 `upstream.json`。先创建草稿、上传完整资产，再转为正式 Release。

只需内置 `GITHUB_TOKEN`，无需提供个人 PAT 或 Docker Hub 密码。写权限仅授予发布 job。官方镜像尚未同步、缺少目标架构或启动测试失败时，工作流失败并保留旧 Release；下次调度会重试。

版本例：上游 `v2026.9.14` → FPK `2026.9.14.1` → GitHub Release `v2026.9.14-fnos.1`。

手动重打同一上游版本：填写 `upstream_tag`，并增加 `package_revision`（如 `2`）。不要覆盖已发布版本。若上游改变版本命名规则，脚本会停止，需人工适配。定时任务跟进“最新正式版”，不回补轮询之间被跳过的历史版；历史版可手动指定 tag 打包。

GitHub 定时任务只在默认分支运行，可能因平台负载延迟。公开仓库 60 天无活动可能暂停定时任务，届时需在 Actions 中重新启用。不会自动升级 NAS 上已安装的应用，也不等于上架飞牛官方应用中心。

## 本地构建

准备 Python 3、Docker CLI + buildx，以及 [官方 fnpack](https://developer.fnnas.com/docs/cli/fnpack/)。镜像检查只访问注册表，不要求本地 Docker daemon；容器冒烟测试需要 daemon。

```bash
python3 scripts/check.py
python3 scripts/release.py build \
  --tag v2026.9.14 --version 2026.9.14.1 \
  --fnpack /absolute/path/to/fnpack
```

产物位于 `dist/`，构建目录为 `.build/package/`。源文件中的 `@@IMAGE@@` 是构建参数，不能直接用于部署。

## 验证范围

自动检查覆盖包结构、生命周期脚本语法、凭据校验、升级保留数据、重复发布判定、官方多架构镜像、fnpack 打包及 amd64 控制台登录。定时 CI 不在 ARM64 runner 做启动测试；2026.9.14.2 已另外通过真实 ARM64 fnOS 设备验证。

**2026.9.14.2 已通过 ARM64 飞牛实机验证**：全新安装、运行状态、停止 / 重新启动、Web 控制台访问、正确及错误密码登录均通过。安装环境为 ARM64、内核 6.18.18.c1090-trim、appcenter-cli 1.0.1。最低 fnOS 版本、桌面图标点击、真实应用升级和卸载保留数据尚未验证；本机 CLI 对已有应用直接返回“已安装”，不能把这次尝试算作升级通过。详见 [实机验证记录](docs/nas-validation.md)。

## 参考

- [飞牛 Docker 应用开发](https://developer.fnnas.com/docs/examples/docker/)
- [飞牛 fnpack](https://developer.fnnas.com/docs/cli/fnpack/)
- [Hermes 官方容器构建](https://github.com/NousResearch/hermes-agent/blob/main/.github/workflows/docker.yml)
- [GitHub schedule 规则](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

提交信息遵循 `@commitlint/config-conventional`。
