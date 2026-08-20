#!/bin/bash
# Comando de inicialização do Azure App Service (Linux).
# Configurar em: Configuration > General settings > Startup Command = "bash startup.sh"
python -m streamlit run Home.py --server.port 8000 --server.address 0.0.0.0 --server.headless true
