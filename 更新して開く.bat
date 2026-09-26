@echo off
cd /d "%~dp0"
python fetch.py
start "" "%~dp0index.html"
