# 开发与贡献

欢迎针对导入、校对、打印和教师资料管理提交问题或改进。请使用原创／合成最小样本复现，不上传学生信息、私人词库、课本全量文件、凭据或备份。较大功能或架构变更请先开 issue 讨论。

## 本地环境

需要 Python 3.13+ 和 Docker。安装锁定依赖，在专用本机 PostgreSQL 容器上开发：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.txt
.venv/bin/python scripts/dev_setup.py
.venv/bin/python -m flask --app englishwords migrate
.venv/bin/python -m pytest -q
```

Docker Desktop 可按实际 context 添加 `--context desktop-linux`。生成器使用独占的新配置和专用容器名；已有 `.local/settings.json` 时退出，不覆盖。数据库仅绑定 `127.0.0.1:55432`，设置和开发登录密码保存在忽略的 `.local/` 内。

集成测试只连接这个本机端口，在独立测试数据库中创建隔离 schema，不使用 SQLite。实际 PDF 检查按环境显式启用。测试 schema 保留供排查，不自动删除已有数据。

## 实际 PDF 检查

原生 macOS 环境可能没有 Pango，使用已构建的应用镜像提供实际排版引擎：

```sh
docker run -d --name vocabulary-pdf-tests --network none \
  -v "$PWD/englishwords:/app/englishwords:ro" \
  --entrypoint sleep englishwords-web infinity
```

将 `ENGLISHWORDS_PDF_TEST_CONTAINER` 设为这个容器名，`ENGLISHWORDS_PDF_QA_PYTHON` 设为已有安装 pdfplumber 的 Python 绝对路径。指定 Docker context 时另设 `ENGLISHWORDS_DOCKER_CONTEXT`。然后运行：

```sh
ENGLISHWORDS_PDF_TEST_CONTAINER=vocabulary-pdf-tests \
ENGLISHWORDS_PDF_QA_PYTHON=/absolute/path/to/python \
.venv/bin/python -m pytest -q tests/test_pdf_layout.py
```

这些检查读取实际 PDF 坐标，验证纵向编号、末页均分和左右格子边界，覆盖长词／例句、分组与单栏／双栏／三栏。没有配置环境时明确跳过，不把跳过描述为 PDF 验收成功。排版修改还需渲染检查页面，不能只看 HTML。

## 修改约定

- 沿用现有 Flask、Jinja、PostgreSQL 和少量原生 JavaScript，保持部署简单。
- 改 schema 时新增 Alembic 迁移，不修改已发布的旧迁移。
- 不自动覆盖课程人工修订，不从未知地区音标猜美音。
- 管理字段和显示名称不能改写冻结源稿、内容快照及校验值。
- PDF 只读取内置字体，不引入任意外部 URL／宿主文件访问。
- 提交前检查依赖变更、公开文件和示例，更新直接受影响的文档，并运行相称测试。

代码贡献使用本仓库的 MIT 许可证；第三方材料必须保留各自授权和来源。
