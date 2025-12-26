FROM python:3.9

COPY . /app
WORKDIR app

COPY ./requirements.txt /app/requirements.txt
RUN pip install -r requirements.txt

ENV QUART_APP=main:app
ENV PYTHONUNBUFFERED=1

CMD [ "python", "-u", "main.py"]
