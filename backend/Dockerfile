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

# Install MP4Box with multiple fallback methods
RUN echo "📦 Installing MP4Box binary..." && \
    # Method 1: Try to install from Ubuntu repository
    (apt-get update && \
     apt-get install -y gpac && \
     which MP4Box && \
     MP4Box -version && \
     echo "✅ MP4Box installed from Ubuntu repository") || \
    \
    # Method 2: Try pre-compiled binary from GPAC project
    (echo "⚠️ Repository install failed, trying pre-compiled binary..." && \
     wget -q https://download.tsi.telecom-paristech.fr/gpac/new_builds/revision_builds/gpac_public/gpac_2.4.0_linux_x86_64.tar.gz -O /tmp/gpac.tar.gz && \
     cd /tmp && \
     tar -xzf gpac.tar.gz && \
     find . -name "MP4Box" -executable -type f | head -1 | xargs -I {} cp {} /usr/local/bin/MP4Box && \
     chmod +x /usr/local/bin/MP4Box && \
     rm -rf /tmp/gpac* && \
     which MP4Box && \
     MP4Box -version && \
     echo "✅ MP4Box installed from pre-compiled binary") || \
    \
    # Method 3: Try alternative download link
    (echo "⚠️ Pre-compiled binary failed, trying alternative source..." && \
     wget -q https://github.com/gpac/gpac/releases/download/v2.4.0/gpac_2.4.0_linux_x86_64.tar.gz -O /tmp/gpac.tar.gz && \
     cd /tmp && \
     tar -xzf gpac.tar.gz && \
     find . -name "MP4Box" -executable -type f | head -1 | xargs -I {} cp {} /usr/local/bin/MP4Box && \
     chmod +x /usr/local/bin/MP4Box && \
     rm -rf /tmp/gpac* && \
     which MP4Box && \
     MP4Box -version && \
     echo "✅ MP4Box installed from alternative source") || \
    \
    # Method 4: Build from source (last resort)
    (echo "⚠️ Binary install failed, trying to build from source..." && \
     apt-get update && \
     apt-get install -y git cmake && \
     git clone https://github.com/gpac/gpac.git /tmp/gpac && \
     cd /tmp/gpac && \
     ./configure && \
     make && \
     make install && \
     ldconfig && \
     which MP4Box && \
     MP4Box -version && \
     rm -rf /tmp/gpac && \
     echo "✅ MP4Box built and installed from source") || \
    \
    # Final fallback: Fail with clear error message
    (echo "❌ All MP4Box installation methods failed!" && \
     echo "❌ Mobile video compatibility fixes will not be available" && \
     echo "❌ Container will continue without MP4Box" && \
     exit 1)

# Clean up apt cache
RUN apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

RUN pip install --upgrade pip wheel setuptools
RUN echo "✅ pip, setuptools, and wheel upgraded"

RUN pip install -r requirements.txt
RUN echo "✅ Python dependencies installed"

CMD ["sleep", "infinity"]
