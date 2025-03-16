from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import subprocess
import logging

# настройка логирования
logging.basicConfig(level=logging.DEBUG)

# экземпляр FastAPI
app = FastAPI()


# модель для входных данных
class PromptRequest(BaseModel):
    prompt: str


# маршрут для генерации текста
@app.post("/generate")
async def generate_text(request: PromptRequest):
    prompt = request.prompt

    try:
        # работа с потоковым выводом
        process = subprocess.Popen(
            ["ollama", "run", "deepseek-r1:14b", prompt],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        # ожидание завершения процеса и получение вывода 
        stdout, stderr = process.communicate()

        # логируем вывод
        logging.debug(f"STDOUT: {stdout}")
        logging.debug(f"STDERR: {stderr}")

        if process.returncode != 0:
            logging.error(f"Ошибка при вызове модели: {stderr}")
            raise HTTPException(status_code=500, detail="Ошибка при вызове модели")

        # возврат результат
        return {"response": stdout}

    except Exception as e:
        logging.error(f"Исключение: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
