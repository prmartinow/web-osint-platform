FROM python:3.12-slim

WORKDIR /app
COPY server.py /app/server.py
COPY static /app/static

ENV DASHBOARD_HOST=0.0.0.0
ENV DASHBOARD_PORT=8091
ENV PYTHONUNBUFFERED=1

EXPOSE 8091
CMD ["python", "/app/server.py"]
