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

## 第二步：连接 GitHub 仓库

### 方式 A：Space 设置里连 GitHub（推荐）

1. Space → **Settings** → **Repository**
2. **Repository URL**：`https://github.com/lixiaowww/JobForecaster-Agent`
3. **Branch**：`main`
4. Save → 自动用仓库根目录的 **`Dockerfile`** 构建

### 方式 B：推送到 HF Git 仓库

```bash
# 在 HF Space 页面复制 git clone 地址后：
git remote add hf https://huggingface.co/spaces/<你的用户名>/JobForecaster-Agent
git push hf main
```

首次 push 若冲突，按 HF 提示 `git push --force`（仅首次）。

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

## 第三步：Secrets（可选）

Space → **Settings** → **Repository secrets**

| Name | 说明 |
|------|------|
| `GROQ_API_KEY` | [Groq 免费 key](https://console.groq.com)，用于 LLM 扩岗位 KB |

无 key 时 Radar / BLS / 情景滑块仍可用。

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
