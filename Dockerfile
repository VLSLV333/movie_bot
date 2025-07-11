FROM python:3.11

WORKDIR /app

COPY . /app
RUN echo "✅ Project files copied to /app"

RUN apt-get update && apt-get install -y \
    ffmpeg \
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

# Clean up locales directory to prevent aiogram_i18n scanning issues
# Note: Keep keys.py as it's needed by the application
RUN find bot/locales -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
RUN find bot/locales -name "*.pot" -delete 2>/dev/null || true
RUN find bot/locales -name "*.pyc" -delete 2>/dev/null || true
RUN rm -f bot/locales/messages.pot 2>/dev/null || true
RUN echo "✅ Locales directory cleaned for aiogram_i18n compatibility (keeping keys.py)"

CMD ["sleep", "infinity"]
