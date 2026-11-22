FROM python:3.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GUNICORN_BIND=0.0.0.0:8000

ARG APP_UID=1000
ARG APP_GID=1000
RUN groupadd -g "$APP_GID" dedo && \
    useradd -r -u "$APP_UID" -g dedo -M -d /srv dedo

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY gunicorn.conf.py .
COPY dedo/ dedo/

USER dedo
EXPOSE 8000
CMD ["gunicorn", "dedo.app:app"]
