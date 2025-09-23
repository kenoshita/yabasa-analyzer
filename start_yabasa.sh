#!/bin/bash
docker build -t yabasa .
docker run --rm -p 8000:8000 yabasa
