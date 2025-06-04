from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from reportQA import MedicalReportGenerator
from dotenv import load_dotenv
from api import report_router, chat_router
import logging
import uvicorn
from collections import defaultdict

import os
import asyncio

from datetime import datetime, timedelta
from contextlib import asynccontextmanager

EXPIRY_SECONDS = 300        # cache entry lifetime (5 minutes)
CLEANUP_INTERVAL = 300       # how often to remove expired entries


load_dotenv()

logger = logging.getLogger("uvicorn")

@asynccontextmanager
async def setup_cache(app: FastAPI):
    api_key = os.getenv("OPENAI_API_KEY")
    model = "gpt-4.1"
    
    def defaultdict_factory():
        return [MedicalReportGenerator(api_key, model), datetime.now() + timedelta(seconds=EXPIRY_SECONDS)]
    
    app.state.report_generators = defaultdict(defaultdict_factory)
    app.state.EXPIRY_SECONDS = EXPIRY_SECONDS

    app.state.cache_lock = asyncio.Lock()
    
    logger.info("Start up function for cache")
    
    async def clean_expired_entries():
        while True:
            await asyncio.sleep(CLEANUP_INTERVAL)
            logger.info("Cleaning expired entries...")
            now = datetime.now()
            async with app.state.cache_lock:
                expired = [key for key, (_, exp) in app.state.report_generators.items() if exp < now]
                for key in expired:
                    del app.state.report_generators[key]
    asyncio.create_task(clean_expired_entries())

    yield
    app.state.report_generators.clear()
    logger.info("Cleared all medical generators.")

app = FastAPI(lifespan=setup_cache)    

# enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(report_router, prefix="/api")
app.include_router(chat_router, prefix="/api")


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)