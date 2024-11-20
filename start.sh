#!/bin/bash
# 啟動 Flask 應用
# gunicorn --bind 0.0.0.0:5000 server:app
gunicorn -k eventlet server:app
