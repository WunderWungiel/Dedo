FROM python:3-bookworm
WORKDIR /srv
COPY ./requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY ./dedo/ ./dedo/
CMD ["gunicorn", "--workers", "8", "--bind", "0.0.0.0:80", "dedo.app:app"]
