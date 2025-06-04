import asyncio
import io
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile, HTTPException, Request
from fastapi.responses import FileResponse
from typing import Optional
from PIL import Image
import imageio.v2 as imageio

from .utils import is_valid_uuid

CURRENT_SCRIPT_PATH = Path(__file__).resolve()
API_DIR = CURRENT_SCRIPT_PATH.parent
PROJECT_ROOT = API_DIR.parent
IMG_STORAGE_PATH = PROJECT_ROOT / "img_store"

report_router = APIRouter()

@report_router.post("/generate-report/")
async def generate_report(
        request: Request,
        file: UploadFile = File(...),
        note: Optional[str] = Form(""),
        user_uuid: str = Form("")
    ):
    if not file.filename.lower().endswith((".jpg", ".jpeg", ".png")):
        raise HTTPException(status_code=400, detail="Only .jpg/.jpeg/.png files are supported")
    if not is_valid_uuid(user_uuid):
        raise HTTPException(status_code=400, detail="Invalid UUID format")
    # TODO: update access time
    async with request.app.state.cache_lock:
        report_generator = request.app.state.report_generators[user_uuid][0]
        request.app.state.report_generators[user_uuid][1] = datetime.now() + timedelta(seconds=request.app.state.EXPIRY_SECONDS)
    
    contents = await file.read()
    
    tmp_in_mem_file = io.BytesIO(contents)

    try:
        img_array = imageio.imread(tmp_in_mem_file)  # ← this is your array
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to process image")

    roles = [
        "Ophthalmologist", "Optometrist", "Glaucoma Specialist",
        "Primary Care Physician", "Ophthalmic Technician", "Pharmacist"
    ]

    print("Generating specialist reports...\n")
    reports, ratio, segmented_image_path = report_generator.generate_reports(tmp_in_mem_file, note, roles)

    print("\nGenerating final synthesis report...\n")
    summary = report_generator.generate_synthesis(reports)

    print("Final Synthesis Report:\n")
    print(summary)

    print("\nGenerating PDF report...\n")
    report_generator.generate_pdf_report(
        image_path=segmented_image_path,
        cup_to_disc_ratio=ratio,
        synthesis_text=summary,
        output_path="output/final_diagnostic_report.pdf"
    )
    print("PDF saved as final_diagnostic_report.pdf")

    return FileResponse(
        path="output/final_diagnostic_report.pdf",
        media_type='application/pdf',
        filename="diagnostic_report.pdf"
    )

@report_router.post("/generate-report-content/")
async def generate_content(
        request: Request,
        file: UploadFile = File(...),
        note: Optional[str] = Form(""),
        user_uuid: str = Form("")
    ):
    if not file.filename.lower().endswith((".jpg", ".jpeg", ".png")):
        raise HTTPException(status_code=400, detail="Only .jpg/.jpeg/.png files are supported")
    if not is_valid_uuid(user_uuid):
        raise HTTPException(status_code=400, detail="Invalid UUID format")
    
    # Start file reading in parallel with retrieving medical report generator
    file_read_task = asyncio.create_task(file.read())
    async with request.app.state.cache_lock:
        report_generator = request.app.state.report_generators[user_uuid][0]
        request.app.state.report_generators[user_uuid][1] = datetime.now() + timedelta(seconds=request.app.state.EXPIRY_SECONDS)

    contents = await file_read_task

    tmp_in_mem_file = io.BytesIO(contents)

    try:
        img_array = imageio.imread(tmp_in_mem_file)
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to process image")

    roles = [
        "Ophthalmologist", "Optometrist", "Glaucoma Specialist",
        "Primary Care Physician", "Ophthalmic Technician", "Pharmacist"
    ]

    print("Generating specialist reports...\n")
    reports, ratio, segmented_image_path = report_generator.generate_reports(tmp_in_mem_file, note, roles)

    print("\nGenerating final synthesis report...\n")
    summary = report_generator.generate_synthesis(reports)

    print("Final Synthesis Report:\n")
    print(summary)
    
    # Add RGB to image
    im = Image.open(segmented_image_path)
    rgb_image_name = f"{uuid.uuid4().hex}"
    im.convert("RGB").save(f"{IMG_STORAGE_PATH}/{rgb_image_name}.jpg")

    return {
        "summary": summary,
        "cup_to_disc_ratio": ratio,
        "img_name": rgb_image_name
    }

@report_router.get("/get-report-image/{img_name}")
async def generate_content(
        img_name: str,
        request: Request,
    ):
    if not os.path.isfile(f"{IMG_STORAGE_PATH}/{img_name}.jpg"):
        raise HTTPException(status_code=400, detail="File not found")
    
    return FileResponse(
        path=f"{IMG_STORAGE_PATH}/{img_name}.jpg"
    )