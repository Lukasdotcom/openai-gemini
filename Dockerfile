FROM python:3.13-alpine

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app.py app.py

EXPOSE 8000

CMD ["gunicorn", "-w 4", "app:app"]