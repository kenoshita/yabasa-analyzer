FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends libfreetype6 libpng16-16 libjpeg62-turbo fonts-noto-cjk && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn","api_app:app","--host","0.0.0.0","--port","8000"]
