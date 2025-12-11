# Use an official Python runtime as a parent image
FROM python:3.11-slim

# install system deps (pngquant + minimal tools)
RUN apt-get update && apt-get install -y \
    pngquant \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy requirements and install
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy the application code
COPY . /app

# Expose port (Render provides $PORT at runtime)
EXPOSE 8000

# Run the uvicorn server. Use ${PORT:-8000} to allow Render to set PORT.
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
