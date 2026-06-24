FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
# ffmpeg drives DeckLink/SDI + audio; mpv (--vo=drm) drives GPU/KMS connectors.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg mpv \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

EXPOSE 9000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9000"]
