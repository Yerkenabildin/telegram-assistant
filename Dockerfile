FROM python:3.9

COPY . /app
WORKDIR app

COPY ./requirements.txt /app/requirements.txt
RUN pip install -r requirements.txt

ENV QUART_APP=main:app

CMD [ "python", "main.py"]
