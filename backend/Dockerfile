FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

# 安装 Python 依赖（使用 PyMySQL，无需单独装 mysqlclient）
RUN pip install --no-cache-dir -r requirements.txt

# 复制后端代码（wxcloudrun app + manage.py + .env）
COPY . .

# 访问端口(外部): 80 → 服务端口(容器内): 8080，gunicorn 必须绑定 8080
EXPOSE 8080

# 启动：先跑 migrate 建表，再启动 Gunicorn
CMD python manage.py migrate --noinput && \
    gunicorn -w 4 -b 0.0.0.0:8080 \
    --timeout 60 \
    --access-logfile - --error-logfile - \
    wxcloudrun.wsgi:application
