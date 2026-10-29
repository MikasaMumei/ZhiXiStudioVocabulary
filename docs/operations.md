# 部署与备份

## 运行环境

已验证 Linux amd64、Docker Compose、PostgreSQL 18。网页和数据库各一个容器；Pango、HarfBuzz 及中文／音标字体在 Web 镜像内。主机不需要安装数据库或 PDF 排版组件。

首次启动步骤见 [README](../README.md)。默认 Web 绑定 `127.0.0.1:8088`，数据库不发布宿主端口。需要内网访问时，在私有 `.env` 中把 `WEB_BIND_IP` 设置为本机对应内网地址。使用 HTTPS 时设置 `COOKIE_SECURE=1`。本项目提供单一教师管理入口，未设计多租户或面向公网的账号系统。

`.env` 含数据库密码、管理密码哈希及会话密钥，不应提交或分享。哈希值中的 `$` 必须保留；使用配置生成器可避免 Compose 的变量插值问题。生成器不会覆盖已有 `.env`。不要输出可能展开凭据的完整配置。

## 首次初始化

```sh
docker compose up -d --wait db
docker compose run --no-deps --name englishwords-migrate web \
  python -m flask --app englishwords migrate
docker compose up -d --no-deps web
```

迁移辅助容器会保留，后续迁移使用不同名称。应用启动不会自动迁移。PostgreSQL 18 的数据卷挂载到 `/var/lib/postgresql`；保留 `postgres-data`，不要在更新时清空数据卷。

## 更新

1. 备份并在独立数据库验证恢复。
2. 获取新代码，构建 Web 镜像。
3. 用新镜像显式执行迁移，成功后更新 Web。
4. 验证登录、真实 PDF 下载、资料管理和旧快照。

```sh
docker compose build web
docker compose run --no-deps --name englishwords-migrate-update web \
  python -m flask --app englishwords migrate
docker compose up -d --no-deps web
```

若使用私有 Compose 覆盖文件，请在备份、迁移和更新时使用相同文件组合。数据库大版本升级应单独安排，不与应用更新合并。

迁移 002 只增加打印回收站时间、管理修订号和索引，不改写旧快照。表锁等待上限为 5 秒，超时后应等待已有操作结束再重试。不会自动删除新增字段；回退旧应用前应考虑它不认识回收站状态，不能据旧界面判断资料已丢失。

## 备份

词库、书本、原始上传文件、导入记录、打印源稿与快照、回收站状态都在 PostgreSQL 内。备份还需保留对应源码／镜像与私有配置，配置和数据备份分开保存。

宿主有 Python 3 时运行：

```sh
python3 scripts/backup.py
```

脚本调用项目数据库容器的 `pg_dump -Fc --no-owner --no-acl -t 'public.*'`，独占创建 `backups/*.dump`，失败会报错。自定义 Compose 组合可通过 `COMPOSE_FILE`、`COMPOSE_PROJECT_NAME` 指定；本机隔离测试也可显式使用 `--context` 和 `--container`。

定期复制备份到独立保存位置，限制文件权限，记录时间和 SHA-256。备份与实际部署配置均不应进入公开仓库。

## 恢复验证

在同版本 PostgreSQL 新建独立空数据库，使用 `pg_restore --no-owner --no-acl --exit-on-error` 导入。核对表数量、人工校订、打印快照校验值，以及回收站状态和恢复能力；不要覆盖当前使用的数据库做试验。恢复旧版本数据后，在隔离库执行对应迁移并检查。

本项目的备份包含全部 `public` 表、索引和约束。若自行新增函数、扩展或其他 schema，需相应扩充备份范围。容器健康和备份文件存在都不能替代恢复验证。
