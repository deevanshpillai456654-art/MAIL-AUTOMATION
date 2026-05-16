.PHONY: help install dev test lint clean run build docker-start docker-stop

help:
	@echo "AI Email Organizer - Make commands"
	@echo "=================================="
	@echo "install      - Install dependencies"
	@echo "dev          - Install development dependencies"
	@echo "test         - Run tests"
	@echo "lint         - Run linting"
	@echo "clean        - Clean cache files"
	@echo "run          - Run the service"
	@echo "build        - Build Docker image"
	@echo "docker-start - Start Docker container"
	@echo "docker-stop  - Stop Docker container"

install:
	cd local-service && pip install -r requirements.txt

dev:
	cd local-service && pip install -r requirements-dev.txt

test:
	cd local-service && pytest ../tests/ -v

lint:
	cd local-service && black --check . && flake8 .

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete

run:
	cd local-service && python run.py start

build:
	docker build -t ai-email-organizer .

docker-start:
	docker-compose up -d

docker-stop:
	docker-compose down