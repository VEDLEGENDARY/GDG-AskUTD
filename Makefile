.PHONY: run test docker openapi

run:
	uvicorn backend.app.main:app --reload --port 8000

test:
	python -m unittest discover -s backend/tests -p "test_api*.py"

docker:
	docker build -t gdg-askutd-api .

openapi:
	python -c "import json; from backend.app.main import app; open('documentation/openapi.json','w',encoding='utf-8').write(json.dumps(app.openapi(),indent=2)+chr(10))"
