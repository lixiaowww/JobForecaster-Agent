# Hugging Face Spaces 部署指南

把 **Streamlit 交互 Dashboard**（Job Radar、准确度、Benchmarks）部署到 [Hugging Face Spaces](https://huggingface.co/spaces) 免费档。

> **GitHub Pages**（[lixiaowww.github.io/JobForecaster-Agent](https://lixiaowww.github.io/JobForecaster-Agent/)）只托管**静态预测报告**。  
> **本指南**部署的是完整 **Streamlit 前端**，两者互补。

---

## 方式 A：从 GitHub 仓库连接（推荐）

仓库已包含 `app.py`、`.streamlit/config.toml` 和合并后的 `requirements.txt`。

### 1. 创建 Space

1. 打开 [huggingface.co/new-space](https://huggingface.co/new-space)
2. 填写：
   | 字段 | 值 |
   |------|-----|
   | Owner | 你的 HF 账号（如 `lixiaowww`） |
   | Space name | `JobForecaster-Agent`（或任意名） |
   | License | 与仓库一致 |
   | Space SDK | **Streamlit** |
   | Space hardware | **CPU basic**（免费） |
3. **不要**选 Docker；选 **Link to a Git repository**（若界面有）
4. 创建

### 2. 连接 GitHub 仓库

1. Space 页面 → **Settings** → **Repository**
2. **Repository URL**：`https://github.com/lixiaowww/JobForecaster-Agent`
3. **Branch**：`main`
4. **App file**：`app.py`
5. Save → 等待自动构建（约 3–8 分钟）

若创建时未出现 Git 连接选项：

1. 先创建空白 Streamlit Space  
2. Settings → Repository → 填上述 URL  
3. App file 设为 `app.py`

### 3. 添加 Secrets（可选）

Space → **Settings** → **Repository secrets**（或 Variables and secrets）

| Name | Value | 说明 |
|------|-------|------|
| `GROQ_API_KEY` | 你的 Groq key | [console.groq.com](https://console.groq.com) 免费档 |

- **有 key**：搜索未知岗位时可 LLM 扩 KB  
- **无 key**：Radar / BLS / 情景滑块仍可用，仅 AI 生成岗位不可用  

Secrets 在 Streamlit 中通过 `os.environ` 读取（与本地 `.env` 相同）。

### 4. 访问

构建成功后：

`https://huggingface.co/spaces/<你的用户名>/JobForecaster-Agent`

（公开 Space 可直接打开；私有 Space 需登录。）

---

## 方式 B：独立 Space 仓库

若不想把整个 GitHub 主仓库连到 HF：

1. 在 HF 新建 Streamlit Space（空白）
2. 将 `deploy/huggingface/README.md` 的内容复制为 Space 根目录 `README.md`（含顶部 YAML）
3. 用 `git clone` Space 仓库，把本项目代码 push 上去（或 GitHub Action 同步）

---

## 文件说明

| 文件 | 作用 |
|------|------|
| `app.py` | HF 入口，`import dashboard` |
| `dashboard.py` | Streamlit 主界面 |
| `requirements.txt` | 含 `-r requirements-dashboard.txt` |
| `.streamlit/config.toml` | 云端 headless + HF 兼容设置 |
| `data/jobs_kb.json` | 岗位知识库（已入库） |
| `data/bls_market_seed.json` | 离线 BLS 实证层 |

---

## 与 GitHub Pages 分工

| 服务 | 内容 | URL 示例 |
|------|------|----------|
| **GitHub Pages** | 每日静态预测报告 | `lixiaowww.github.io/JobForecaster-Agent/` |
| **HF Spaces** | 交互 Dashboard | `huggingface.co/spaces/lixiaowww/JobForecaster-Agent` |

---

## 常见问题

### 构建失败 `ModuleNotFoundError`

确认 Space 使用仓库根目录的 `requirements.txt`，且已 push 含 `-r requirements-dashboard.txt` 的版本。

### 页面空白或 502

- 查看 Space **Logs** 标签  
- 首次冷启动可能 1–2 分钟  
- 免费档闲置后会休眠，再次打开需等待唤醒  

### Accuracy 页数据为空

正常：Space 上默认无 `data/forecaster.db`（未提交 git）。  
预测数据在 **GitHub Pages 报告** 或本地 `run.py once` 产生；HF 主要展示 **Job Radar**。

### 限制免费档

- CPU / 内存有限，GMM `n_bootstrap` 在侧边栏改小可加速  
- 不适合高并发；个人 demo / donation 项目足够  

---

## 推送更新

主仓库更新后，若 Space 已连 GitHub，**push 到 `main` 会自动重建**：

```bash
git add app.py docs/HUGGINGFACE.md .streamlit/config.toml requirements.txt
git commit -m "Add Hugging Face Spaces Streamlit deploy"
git push origin main
```

---

## 相关文档

- [docs/DEPLOY.md](DEPLOY.md) — GitHub Pages 零成本部署  
- [README.md](../README.md) — 本地 `streamlit run dashboard.py`
