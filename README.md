# 智习工作室词表 · ZhiXi Studio Vocabulary

轻量、自托管的教师英语词表整理与 A4 PDF 制作工具。使用 **PostgreSQL + Flask + Docker Compose**，界面以中文为主，美式音标优先。

**整理词库 → 按书本／单元选词 → 生成三种 PDF → 打印或长期保存。**

## 能做什么

- 从 Excel `.xlsx` 或 UTF-8 CSV 批量导入，预览差异、避免重复导入，保护人工修改。
- 按学段、年级、教材版本、书本和单元管理；支持首字母与关键词筛选、字母排序和组内乱序。
- 同一单词可在不同书本保留不同课程义、读音或例句；美音缺失时留空，不以英音替代。
- 直接生成内嵌字体的 A4 PDF：中英对照、看英写中、看中写英。
- 每页先纵向填满左栏，再接右栏；各栏均分条目，共享行高，长词换行后横线仍对齐。
- 打印资料使用内容快照；可搜索、分页、修改显示名称、单份／批量移入回收站并恢复。

本项目面向教师整理与打印，不包含学生账号、在线学习追踪、音频、比赛或第三方背词服务接入。

## 不附带教材词库

公开仓库和镜像只包含应用、字体许可证及少量[原创示例 CSV](englishwords/static/sample.csv)。**不附带商业词典数据、课本全量词表、私人导入文件或实际部署数据。** 请导入自己有权使用的资料，分别记录教材版本与来源。

## Docker 快速开始

以下命令适用于 Bash 和已安装 Docker Compose 的环境，已验证 Linux amd64。需要能构建镜像的网络条件；镜像内安装 PDF 排版库，宿主机不需要安装 Pango 或 Python 包。

```sh
git clone https://github.com/MikasaMumei/ZhiXiStudioVocabulary.git
cd ZhiXiStudioVocabulary
docker build -t englishwords-web .
```

在镜像里运行配置生成器，交互设置自己的管理密码。它只创建 `.env`，不会覆盖已有配置；生成的数据库密码和密钥不输出到终端。

```sh
docker run -it --name englishwords-config --network none \
  --user "$(id -u):$(id -g)" \
  -v "$PWD:/workspace" -w /workspace \
  --entrypoint python englishwords-web scripts/make_env.py
```

启动数据库、执行迁移，再启动网页：

```sh
docker compose up -d --wait db
docker compose run --no-deps --name englishwords-migrate web \
  python -m flask --app englishwords migrate
docker compose up -d --no-deps web
```

访问 **http://127.0.0.1:8088/**，使用刚设置的密码登录。首次安装是空库，可从“批量导入”下载示例并试用。初始化辅助容器会保留，重复执行时请使用不同的容器名称。

默认网页只绑定本机，数据库不发布宿主端口。内网共享、更新及备份见[部署维护](docs/operations.md)。Python 模块、Compose 项目和数据卷使用 `englishwords` 名称；更改仓库名称不会创建另一套运行数据。

## 文档

- [使用指南](docs/user-guide.md)：导入、整理、打印和回收站。
- [数据规范](docs/data-spec.md)：课程覆盖值、导入更新与来源。
- [PDF 排版](docs/printing.md)：三张表、分页和快照边界。
- [部署与备份](docs/operations.md)：配置、迁移、更新及恢复。
- [开发与贡献](CONTRIBUTING.md)：本地 PostgreSQL 测试和 PDF 检查。

## 技术与验证

Python、Flask、SQLAlchemy／psycopg、Alembic、openpyxl、WeasyPrint；PostgreSQL 18；原生 HTML/CSS 和少量 JavaScript。依赖版本和哈希已锁定，无前端构建链。

已在真实 PostgreSQL 上验证导入事务、修订冲突、快照保留和管理恢复；实际 PDF 检查覆盖单栏／双栏／三栏、长词与例句换行、分页、编号及网格对齐。大份资料建议按单元生成；单次 PDF 任务超时为 90 秒。未宣称覆盖所有系统或打印机。

## 许可证

应用代码与原创示例使用 [MIT](LICENSE)。内置 Noto 字体采用 SIL OFL 1.1，许可证随字体保留。第三方资料不适用本项目的软件许可证，见 [Third-party notices](THIRD-PARTY-NOTICES.md)。
