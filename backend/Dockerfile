FROM python:3.12-slim

WORKDIR /app

# 安装 MySQL 客户端依赖（mysqlclient 需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    default-libmysqlclient-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir mysqlclient

# 复制后端代码（wxcloudrun app + manage.py + .env）
COPY . .

# 访问端口(外部): 80 → 服务端口(容器内): 8080，gunicorn 必须绑定 8080
EXPOSE 8080

# 启动 Gunicorn，监听 8080 端口（与云托管服务端口一致）
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8080", \
     "--timeout", "60", \
     "--access-logfile", "-", "--error-logfile", "-", \
     "wxcloudrun.wsgi:application"]
