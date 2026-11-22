import os

# The image sets GUNICORN_BIND=0.0.0.0:8000; the default keeps a host install
# behind its nginx proxy.
bind = os.environ.get("GUNICORN_BIND") or "127.0.0.1:8000"
workers = int(os.environ.get("WEB_CONCURRENCY", 4))
worker_class = "gthread"
threads = 4
control_socket_disable = True
