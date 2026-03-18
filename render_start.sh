#!/bin/bash
# Render.com startup script for Google Timeline Analytics
# These flags prevent cold-start timeout and fix headless browser rendering

streamlit run app.py \
  --server.port "${PORT:-8501}" \
  --server.address 0.0.0.0 \
  --server.headless true \
  --server.enableCORS false \
  --server.enableXsrfProtection false \
  --server.maxUploadSize 200 \
  --browser.gatherUsageStats false
