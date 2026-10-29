FROM python:3.11-slim

# Install ffmpeg and ca-certificates
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY yt_music_server.py .

ENV PORT=8080
EXPOSE 8080

CMD ["python", "yt_music_server.py"]
