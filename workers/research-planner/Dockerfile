FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app
COPY research_planner.py /app/research_planner.py

USER nobody
ENTRYPOINT ["python", "/app/research_planner.py"]
