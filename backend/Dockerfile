# app/backend/Dockerfile
FROM python:3.11

WORKDIR /app

RUN pip install -U camoufox[geoip]
ENV CAMOUFOX_CACHE_DIR=/usr/local/share/camoufox
RUN python3 -m camoufox fetch
RUN echo "✅ Camoufox installed and browser binary fetched"

COPY . /app
RUN echo "✅ Project files copied to /app"

RUN apt-get update && apt-get install -y \
    ffmpeg \
    wget \
    unzip \
    build-essential \
    gcc \
    python3-dev \
    libffi-dev \
    libssl-dev \
    libgtk-3-0 \
    libx11-xcb1 \
    libdbus-glib-1-2 \
    libasound2 \
    libnss3 \
    libxss1 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libxext6 \
    libxfixes3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libglib2.0-0 \
    ca-certificates \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*
RUN echo "✅ Camoufox browser dependencies installed"

RUN pip install --upgrade pip wheel setuptools
RUN echo "✅ pip, setuptools, and wheel upgraded"

RUN pip install -r requirements.txt
RUN echo "✅ Python dependencies installed"

RUN pip install playwright
RUN playwright install chromium
RUN playwright install firefox
RUN echo "✅ Playwright installed with Chromium browser"

# Always install the latest yt-dlp nightly version
RUN pip install -U --pre "yt-dlp[default]"
RUN yt-dlp --version

# Final cleanup
RUN apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

CMD ["sleep", "infinity"]
