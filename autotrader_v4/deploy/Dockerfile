FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
RUN useradd --create-home --uid 10001 app
COPY autotrader_v4/deploy/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY autotrader_v4 /srv/autotrader_v4
USER app
EXPOSE 8080
CMD ["python", "-m", "uvicorn", "autotrader_v4.web:app", "--host", "0.0.0.0", "--port", "8080"]
