FROM python:3.12-slim
WORKDIR /app
COPY server.py academy.py hr_assistant.py demo_data.py tasks.py /app/
COPY static /app/static
COPY content /app/content
RUN mkdir /app/data && useradd --system --uid 10001 janamen && chown -R janamen /app
USER janamen
EXPOSE 8765
CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8765"]
