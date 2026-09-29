FROM python:3.12-slim

# Hugging Face Spaces runs the container as user 1000 and expects the app on port 7860
RUN useradd -m -u 1000 user
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=user . .
RUN mkdir -p results/jobs results/batches && chown -R user:user /home/user/app
USER user

ENV HOST=0.0.0.0 PORT=7860 PYTHONUNBUFFERED=1
EXPOSE 7860
CMD ["python", "app.py"]
