# Morgenbrief: bewusst ohne zusaetzliche Python-Pakete, nur die Standardbibliothek.
# Der Bau haengt damit allein vom offiziellen Python-Image ab.
ARG BUILD_FROM
ARG BUILD_ARCH
ARG BUILD_VERSION
FROM python:3.13-alpine
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Europe/Berlin
RUN apk add --no-cache tzdata
WORKDIR /app
COPY app/ /app/
CMD ["python3", "/app/main.py"]
