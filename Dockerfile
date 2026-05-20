FROM python:3.12-slim

WORKDIR /app

# 安装 MySQL 客户端依赖（mysqlclient 需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    default-libmysqlclient-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# 复制后端子目录到容器
COPY backend/ .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir mysqlclient

# CloudBase 云托管默认端口 8080
EXPOSE 8080

# 启动 Gunicorn
# wxcloudrun 是 backend/ 下的 Django app
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8080", \
     "--access-logfile", "-", "--error-logfile", "-", \
     "wxcloudrun.wsgi:application"]
