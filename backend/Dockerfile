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
RUN echo "✅ System build tools installed"

# Install pre-compiled MP4Box binary (with fallback)
RUN echo "📦 Installing MP4Box binary..." && \
    (wget -q https://download.tsi.telecom-paristech.fr/gpac/new_builds/revision_builds/gpac_public/gpac_2.4.0_linux_x86_64.tar.gz -O /tmp/gpac.tar.gz && \
     cd /tmp && \
     tar -xzf gpac.tar.gz && \
     find . -name "MP4Box" -executable -type f | head -1 | xargs -I {} cp {} /usr/local/bin/MP4Box && \
     chmod +x /usr/local/bin/MP4Box && \
     rm -rf /tmp/gpac* && \
     echo "✅ MP4Box installed successfully") || \
    echo "⚠️ MP4Box installation failed - will use Python fallback"

RUN pip install --upgrade pip wheel setuptools
RUN echo "✅ pip, setuptools, and wheel upgraded"

RUN pip install -r requirements.txt
RUN echo "✅ Python dependencies installed"

CMD ["sleep", "infinity"]
