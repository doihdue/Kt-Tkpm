# Sử dụng một phiên bản Python hiện đại tương thích với Django 5+
FROM python:3.11-slim

# Đặt các biến môi trường để tối ưu hóa
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Đặt thư mục làm việc
WORKDIR /app

# Cài đặt các gói hệ thống cần thiết cho mysqlclient
RUN apt-get update && apt-get install -y \
    pkg-config \
    default-libmysqlclient-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Cài đặt các thư viện cần thiết
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Sao chép toàn bộ mã nguồn của service vào
COPY . .