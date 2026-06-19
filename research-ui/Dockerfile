FROM python:3.12-slim

WORKDIR /app
COPY server.py /app/server.py
COPY static /app/static

ENV RESEARCH_UI_HOST=0.0.0.0
ENV RESEARCH_UI_PORT=18192
ENV PYTHONUNBUFFERED=1

EXPOSE 18192
CMD ["python", "/app/server.py"]
