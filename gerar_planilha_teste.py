"""Gera uma planilha de exemplo (.xlsx) com as 3 abas esperadas pelo app, para testes manuais."""
import pandas as pd

hierarquia = pd.DataFrame([
    {"Código do Vendedor": "V001", "Nome_do_Vendedor": "Ana Souza", "Nome do Supervisor": "Carlos Lima", "Descrição Regional": "Sudeste"},
    {"Código do Vendedor": "V002", "Nome_do_Vendedor": "Bruno Alves", "Nome do Supervisor": "Carlos Lima", "Descrição Regional": "Sudeste"},
    {"Código do Vendedor": "V003", "Nome_do_Vendedor": "Camila Reis", "Nome do Supervisor": "Diego Farias", "Descrição Regional": "Sul"},
])

produtos = pd.DataFrame([
    {"Código do Produto": "P100", "Descrição do Produto": "Parmesão Ralado 100g", "Descrição do Grupo": "Parmesão"},
    {"Código do Produto": "P200", "Descrição do Produto": "Gouda Fatiado 200g", "Descrição do Grupo": "Gouda"},
    {"Código do Produto": "P300", "Descrição do Produto": "Mussarela Peça 1kg", "Descrição do Grupo": "Mussarela"},
])

volumes = pd.DataFrame([
    {"Chave": "C001", "Nome do Cliente": "Mercado Bom Preço", "Descrição Regional": "Sudeste", "Nome do Supervisor": "Carlos Lima",
     "Descrição do Grupo": "Parmesão", "Código do Vendedor": "V001", "Nome_do_Vendedor": "Ana Souza",
     "Código do Produto": "P100", "Descrição do Produto": "Parmesão Ralado 100g",
     "Media 6 Meses Kg": 500, "Media 3 Meses Kg": 480, "Mínimo": 400, "Máximo": 600, "Ultimo Mês": 520},
    {"Chave": "C001", "Nome do Cliente": "Mercado Bom Preço", "Descrição Regional": "Sudeste", "Nome do Supervisor": "Carlos Lima",
     "Descrição do Grupo": "Mussarela", "Código do Vendedor": "V001", "Nome_do_Vendedor": "Ana Souza",
     "Código do Produto": "P300", "Descrição do Produto": "Mussarela Peça 1kg",
     "Media 6 Meses Kg": 300, "Media 3 Meses Kg": 200, "Mínimo": 150, "Máximo": 350, "Ultimo Mês": 300},
    {"Chave": "C002", "Nome do Cliente": "Supermercado Estrela", "Descrição Regional": "Sudeste", "Nome do Supervisor": "Carlos Lima",
     "Descrição do Grupo": "Gouda", "Código do Vendedor": "V002", "Nome_do_Vendedor": "Bruno Alves",
     "Código do Produto": "P200", "Descrição do Produto": "Gouda Fatiado 200g",
     "Media 6 Meses Kg": 220, "Media 3 Meses Kg": 210, "Mínimo": 150, "Máximo": 300, "Ultimo Mês": 250},
    {"Chave": "C003", "Nome do Cliente": "Atacado Sul", "Descrição Regional": "Sul", "Nome do Supervisor": "Diego Farias",
     "Descrição do Grupo": "Parmesão", "Código do Vendedor": "V003", "Nome_do_Vendedor": "Camila Reis",
     "Código do Produto": "P100", "Descrição do Produto": "Parmesão Ralado 100g",
     "Media 6 Meses Kg": 700, "Media 3 Meses Kg": 650, "Mínimo": 500, "Máximo": 900, "Ultimo Mês": 800},
])

with pd.ExcelWriter("planilha_teste.xlsx", engine="xlsxwriter") as writer:
    hierarquia.to_excel(writer, sheet_name="Hierarquia", index=False)
    produtos.to_excel(writer, sheet_name="Produtos", index=False)
    volumes.to_excel(writer, sheet_name="Volumes", index=False)

print("planilha_teste.xlsx gerada.")
