
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy backend requirements
COPY gov-agent-backend/requirements.txt /app/requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright
RUN pip install --no-cache-dir playwright

# Install Chromium and required Linux dependencies
RUN playwright install --with-deps chromium

# Copy browser agent
COPY browser_agent/ /app/browser_agent/

# Copy FastAPI backend
COPY gov-agent-backend/ /app/gov-agent-backend/

# Allow Python to import both packages
ENV PYTHONPATH=/app

# Disable Python buffering
ENV PYTHONUNBUFFERED=1

# Move into backend directory
WORKDIR /app/gov-agent-backend

# Render port
EXPOSE 8000

# Start FastAPI
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
