FROM python:3.11-slim

WORKDIR /app

# 安装中文字体 (用于 PDF 报告渲染)
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制源码
COPY . .

# 创建运行时数据目录
RUN mkdir -p data/reports data/raw_documents

EXPOSE 8008

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8008"]
