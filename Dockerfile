FROM python:3.13-slim
WORKDIR /app

# Parches de seguridad del sistema base
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# pip y setuptools solo hacen falta para instalar: se quitan de la imagen final
# para eliminar sus dependencias vendorizadas (urllib3, msgpack, etc.)
COPY requirements.txt .
RUN pip --no-cache-dir install -r requirements.txt \
    && pip uninstall -y pip setuptools wheel

COPY main.py .

# Usuario sin privilegios: el proceso no corre como root
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir /data \
    && chown app:app /data

ENV DATA_DIR=/data
VOLUME /data

USER 10001:10001

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
