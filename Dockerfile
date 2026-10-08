# Ikkala backend (api va media) uchun bitta image; qaysi biri ishlashini compose'dagi command hal qiladi.
FROM python:3.13-slim

WORKDIR /app

COPY api/requirements.txt api-requirements.txt
COPY media/requirements.txt media-requirements.txt
RUN pip install --no-cache-dir -r api-requirements.txt -r media-requirements.txt

COPY api api
COPY media media
COPY web web
