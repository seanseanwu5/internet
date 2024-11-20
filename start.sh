#!/bin/bash
gunicorn -k eventlet -w 1 server:app --bind 0.0.0.0:$PORT
