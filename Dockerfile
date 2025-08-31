FROM python:3.13-slim

WORKDIR /app

COPY app /app
COPY requirements.txt /app/

RUN pip install --upgrade pip && pip install -r requirements.txt

EXPOSE 5001

CMD ["python", "listener_review_bot.py"]