FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
# 前端构建产物直接打进镜像，由 FastAPI 托管（单容器同时出 API 与页面）
COPY frontend-dist ./frontend-dist

ENV IHUB_DATA_DIR=/app/data
EXPOSE 8000

# 注意：必须单 worker（SSE 事件总线为进程内实现）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-proxy-headers"]
