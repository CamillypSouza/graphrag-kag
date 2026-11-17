# Imagem da interface (perfil "app" do docker-compose). O Neo4j roda no serviço próprio.
# Instalação editável: config.ROOT aponta para /app, onde ficam data/ e .env.
FROM python:3.13-slim
WORKDIR /app
ENV PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1
COPY pyproject.toml ./
COPY src ./src
RUN pip install --extra-index-url https://download.pytorch.org/whl/cpu torch && pip install -e .
EXPOSE 8501
CMD ["streamlit", "run", "src/jurigraph/ui/app.py", "--server.address=0.0.0.0", "--server.headless=true"]
