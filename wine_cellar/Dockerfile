FROM python:3.12-alpine
RUN pip install --no-cache-dir openpyxl==3.1.5
COPY app /app
COPY config.yaml /app/config.yaml
# barcode reader for phones without a built-in BarcodeDetector (the app falls back to the CDN if this fails)
RUN mkdir -p /app/static/vendor && python -c "import urllib.request as u; u.urlretrieve('https://cdn.jsdelivr.net/npm/@zxing/library@0.21.3/umd/index.min.js', '/app/static/vendor/zxing.min.js')" \
    || echo "zxing download failed; the app loads it from the CDN instead"
WORKDIR /app
ENV WINE_DB=/data/wine_cellar.db \
    WINE_PORT=8099 \
    PYTHONDONTWRITEBYTECODE=1
CMD ["python", "-u", "/app/server.py"]
