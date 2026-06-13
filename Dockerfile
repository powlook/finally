# Multi-stage Dockerfile for FinAlly — AI Trading Workstation

# Stage 1: Build static frontend React application
FROM node:20-slim AS frontend-builder
WORKDIR /build

# Copy frontend config & dependencies
COPY frontend/package*.json ./
RUN npm install

# Copy source code and build export
COPY frontend/ ./
RUN npm run build

# Stage 2: Build Python FastAPI application
FROM python:3.12-slim
WORKDIR /app

# Install uv package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy backend dependencies definition
COPY backend/pyproject.toml backend/uv.lock ./backend/
WORKDIR /app/backend

# Sync dependencies (including lock file check)
RUN uv sync --frozen --no-dev --no-install-project

# Copy backend app source code
COPY backend/app/ ./app/

# Copy compiled frontend static assets from Stage 1 into the backend static folder
COPY --from=frontend-builder /build/out/ ./static/

# Configure SQLite database path for container volume mount
ENV DB_PATH=/app/db/finally.db
ENV STATIC_DIR=/app/backend/static

# Expose server port
EXPOSE 8000

# Start server using uvicorn running through uv
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
