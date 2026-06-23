FROM python:3.12-slim

# ffprobe (from ffmpeg) is required for media probing.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        bash \
        pciutils \
        usbutils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY deploy/discover.sh ./deploy/discover.sh
RUN chmod +x ./deploy/discover.sh

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
