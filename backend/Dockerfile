# psycopg2-binary ships precompiled wheels, so no build toolchain (gcc/libpq-dev) needed —
# keeps this image smaller and the build faster.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["sh", "./entrypoint.sh"]
