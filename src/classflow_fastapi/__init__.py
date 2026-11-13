from fastapi import FastAPI
from pydantic import BaseModel  

app = FastAPI(
    title="ClassFlow FastAPI",
    version="0.1.0",
)

class HealthCheckResponse(BaseModel):
    status: str
    
    
 @app.get("/health", response_model=HealthCheckResponse)
    def health_check():
        return HealthCheckResponse(status="healthy")    

