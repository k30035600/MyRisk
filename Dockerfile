# MyRisk (금융거래 통합정보) - Flask 앱
FROM python:3.11-slim

WORKDIR /app

# Railway 등 Linux에서 한글 깨짐 방지
ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUTF8=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["python", "-X", "utf8", "start_web.py"]
