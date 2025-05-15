FROM python:3.11

WORKDIR /app

COPY . /app
RUN echo "✅ Project files copied to /app"

RUN apt-get update && apt-get install -y \
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

RUN pip install --upgrade pip wheel setuptools
RUN echo "✅ pip, setuptools, and wheel upgraded"

RUN pip install -r requirements.txt
RUN echo "✅ Python dependencies installed"

RUN pip install -U camoufox[geoip]
RUN python3 -m camoufox fetch
RUN echo "✅ Camoufox installed and browser binary fetched"

CMD ["sleep", "infinity"]
