FROM python:3.12-slim
ENV TZ=Europe/Madrid PYTHONUNBUFFERED=1 DBLOCATION=/data/punsdb.db
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY punsbot.py .
COPY defaultpuns ./defaultpuns
VOLUME /data
CMD ["python", "punsbot.py"]
