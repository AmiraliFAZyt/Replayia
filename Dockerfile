FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements*.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py ./
COPY static ./static
RUN useradd --uid 10001 --create-home replya && mkdir -p /var/data/replya && chown -R replya:replya /var/data /app
USER replya
EXPOSE 10000
CMD ["sh", "-c", "exec uvicorn server:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1 --proxy-headers --forwarded-allow-ips='*' --no-access-log --log-level critical"]
