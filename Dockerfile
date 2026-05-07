FROM python:3.12.7-slim

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# base packages
RUN apt update \
  && apt install -y python3-dev default-libmysqlclient-dev build-essential git redis-tools pkg-config libmagic1 file \
  && rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /opt/project

# Install dependencies
COPY requirements.txt /opt/project/
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy the project
COPY . /opt/project/

EXPOSE 8007

# Run the Django development server
CMD ["python", "manage.py", "runserver", "--noreload", "--insecure", "0.0.0.0:8007"]
