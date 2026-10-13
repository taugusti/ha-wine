FROM python:3.12-alpine
RUN pip install --no-cache-dir openpyxl==3.1.5
COPY app /app
WORKDIR /app
ENV VIN_DB=/data/vinkaelder.db \
    VIN_PORT=8099 \
    PYTHONDONTWRITEBYTECODE=1
CMD ["python", "-u", "/app/server.py"]
