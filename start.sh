#!/bin/bash
gunicorn -k eventlet -w 1 app.__init__:app
