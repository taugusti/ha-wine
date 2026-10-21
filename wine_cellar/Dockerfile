FROM python:3.12-alpine
RUN apk add --no-cache openssl
RUN pip install --no-cache-dir openpyxl==3.1.5
COPY app /app
COPY config.yaml /app/config.yaml
WORKDIR /app
ENV WINE_DB=/data/wine_cellar.db \
    WINE_PORT=8099 \
    WINE_DIRECT_PORT=8100 \
    PYTHONDONTWRITEBYTECODE=1
CMD ["python", "-u", "/app/server.py"]
