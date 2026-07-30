# -*- coding: utf-8 -*-
"""
Imports explícitos para PyInstaller.
Garante que todas as dependências são detectadas durante o build.
"""

# Hypercorn (servidor ASGI)
import hypercorn
import hypercorn.asyncio
import hypercorn.config

# FastAPI / Starlette
import fastapi
import starlette
import starlette.routing
import starlette.responses
import starlette.staticfiles
import starlette.middleware

# Multipart (upload de arquivos)
import multipart
import multipart.multipart

# HTTP
import h11

# Outros
import openpyxl
import requests
import selenium
import webdriver_manager
import pandas
