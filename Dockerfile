FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 5001
# --timeout 300: o pacote do mês baixa dezenas de arquivos do Storage antes de
# devolver o zip; com os 30 s padrão do gunicorn o worker era morto no meio e
# a tela mostrava erro sem mensagem. O download em paralelo (pacote_zip) reduz
# o tempo; o timeout maior é a rede de segurança.
CMD ["gunicorn", "-w", "2", "--threads", "4", "--timeout", "300", "-b", "0.0.0.0:5001", "app:create_app()"]
