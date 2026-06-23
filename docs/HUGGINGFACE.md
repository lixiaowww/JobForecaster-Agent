# Hugging Face Spaces 部署指南

把 **Streamlit 交互 Dashboard** 部署到 [Hugging Face Spaces](https://huggingface.co/spaces) 免费档。

> **重要（2025 年起）**：Hugging Face **已移除原生 Streamlit SDK**（[changelog 2025-04-30](https://huggingface.co/docs/hub/spaces-changelog)）。  
> 创建 Space 时请选择 **Docker**，不要找 Streamlit 选项。

| 服务 | 内容 |
|------|------|
| [GitHub Pages](https://lixiaowww.github.io/JobForecaster-Agent/) | 静态每日预测报告 |
| **HF Spaces** | 交互 Streamlit（Job Radar 等） |

---

## 第一步：创建 Space（选 Docker）

1. 打开 [huggingface.co/new-space](https://huggingface.co/new-space)
2. 填写：

| 字段 | 选择 |
|------|------|
| Space name | `JobForecaster-Agent` |
| **SDK** | **Docker** ← 不是 Streamlit |
| Hardware | **CPU basic**（免费） |
| License | 与仓库一致 |

3. 点 **Create Space**

---

## 第二步：GitHub Actions 自动同步（推荐）

每次 `git push origin main` 后，自动把代码同步到 HF Space。

### 1. 在 Hugging Face 创建 Write Token

| 步骤 | 位置 |
|------|------|
| 平台 | **[huggingface.co](https://huggingface.co)**（不是 GitHub） |
| 路径 | 头像 → **Settings** → **Access Tokens** → **Create new token** |
| 权限 | **Write** |
| 复制 | 生成后立刻保存（只显示一次） |

### 2. 在 GitHub 添加 Secret

| 步骤 | 位置 |
|------|------|
| 平台 | **[GitHub](https://github.com)** 仓库 `lixiaowww/JobForecaster-Agent` |
| 路径 | **Settings** → **Secrets and variables** → **Actions** → **New repository secret** |
| Name | `HF_TOKEN`（必须完全一致） |
| Value | 粘贴上一步的 **Hugging Face Write token** |

### 3. 触发同步

```bash
git push origin main
```

或 GitHub → **Actions** → **Sync to Hugging Face Space** → **Run workflow**

Workflow：`.github/workflows/sync-hf-space.yml`（使用官方 `huggingface/hub-sync` 上传，含 `README.md` 顶部 YAML）

目标 Space：`https://huggingface.co/spaces/lixiaowww/JobForecaster-Agent`

> 若 Space 报 `Missing configuration in README`，说明 HF 上 README 还是旧版；确认 `HF_TOKEN` 已设且 workflow 成功跑完。

### 方式 B：本地手动 push（备用）

```bash
huggingface-cli login   # 粘贴 Hugging Face Write token
git remote add hf https://huggingface.co/spaces/lixiaowww/JobForecaster-Agent
git push hf main --force
```

---

## 仓库里已准备好的文件

| 文件 | 作用 |
|------|------|
| `Dockerfile` | Streamlit + 依赖，`EXPOSE 8501` |
| `app.py` | 入口（`import dashboard`） |
| `.dockerignore` | 排除 `venv/`、`.env` 等 |
| `requirements.txt` | 含 Streamlit 依赖 |

`README.md` 顶部 **无需** YAML（选 Docker SDK 创建即可）。  
若 HF 要求 metadata，把 `deploy/huggingface/SPACE_README.md` 的 YAML 块合并进 Space 的 README。

---

## 第三步：HF Space Secrets（可选，LLM 用）

| 平台 | 路径 | Name | 来源 |
|------|------|------|------|
| **Hugging Face** Space | Space → **Settings** → **Repository secrets** | `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) |

无 key 时 Radar / BLS / 情景滑块仍可用。

---

## Token 对照表（别混）

| Secret 名 | 在哪创建 | 填在哪 | 用途 |
|-----------|----------|--------|------|
| `HF_TOKEN` | **Hugging Face** Access Tokens | **GitHub** → Secrets → Actions | Actions 同步代码到 HF |
| `GROQ_API_KEY` | **Groq** Console | **HF Space** Secrets（或 GitHub Secrets 给日更） | LLM |
| GitHub PAT | **GitHub** | 本地 `git push origin` | 推 GitHub，与 HF 无关 |

---

## 构建成功标志

- Logs 出现 `You can now view your Streamlit app`
- 健康检查：`/_stcore/health` 通过
- 访问：`https://huggingface.co/spaces/<用户名>/JobForecaster-Agent`

首次或休眠唤醒后可能等 1–3 分钟。

---

## 常见问题

### 创建页没有 Streamlit？

正常。请选 **Docker**，本项目已提供 `Dockerfile`（[官方说明](https://huggingface.co/docs/hub/spaces-sdks-docker)）。

### 黑屏 / 蓝屏（Running 但内容区全黑）

多为 **Streamlit 在 HF iframe 里未关闭 XSRF/CORS**，前端 JS 无法加载（与 Groq key 无关）。

已在本仓库 `Dockerfile` 中通过启动参数修复。请 `git push origin main` 触发重建，或 Actions → **Sync to Hugging Face Space**。

本地自检：浏览器 DevTools → **Network**，若大量 `*.js` / `*.css` 为 404，即为此问题。

### 503 / Preparing Space 一直转

检查三处端口一致为 **8501**：

- `Dockerfile` → `EXPOSE 8501` 与 `ENTRYPOINT ... --server.port=8501`
- Space README YAML（若有）→ `app_port: 8501`
- 不要用 `app_port: 7860`（那是 Gradio 默认）

### 构建失败 ModuleNotFoundError

确认 `main` 分支已 push 最新 `requirements.txt`（含 `-r requirements-dashboard.txt`）。

### Accuracy 页为空

Space 无 `forecaster.db`（未入库）。预测历史见 GitHub Pages；HF 主要用于 **Job Radar**。

---

## 本地对比

```bash
# 本地 Streamlit（与 HF 相同 UI）
streamlit run app.py

# 本地模拟 Docker 构建（可选）
docker build -t jobforecaster .
docker run -p 8501:8501 jobforecaster
```

---

## 推送更新

```bash
git push origin main   # 若 Space 已连 GitHub，会自动重建
```

---

## 相关

- [docs/DEPLOY.md](DEPLOY.md) — GitHub Pages
- [Docker Spaces 文档](https://huggingface.co/docs/hub/spaces-sdks-docker)
