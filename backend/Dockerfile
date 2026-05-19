FROM python:3.10-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libmariadb-dev \
    && rm -rf /var/lib/apt/lists/*

# 设置 pip 镜像
RUN pip config set global.index-url https://mirrors.tencent.com/pypi/simple \
    && pip config set global.trusted-host mirrors.tencent.com

# 拷贝依赖文件并安装
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# 拷贝项目代码
COPY . .

# 收集静态文件
RUN python manage.py collectstatic --noinput || true

# 暴露端口（容器内部监听端口）
EXPOSE 80

# 启动命令（使用 gunicorn 生产服务器）
CMD ["gunicorn", "--bind", "0.0.0.0:80", "--workers", "2", "--timeout", "60", "wxcloudrun.wsgi:application"]
