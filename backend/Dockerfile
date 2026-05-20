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

# 云托管服务端口配置为 80，gunicorn 必须绑定 0.0.0.0:80
EXPOSE 80

# 启动 Gunicorn，监听 80 端口（与云托管 container.config.json containerPort 一致）
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:80", \
     "--timeout", "60", \
     "--access-logfile", "-", "--error-logfile", "-", \
     "wxcloudrun.wsgi:application"]
