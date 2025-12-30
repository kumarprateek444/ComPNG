import os
import json
import tempfile
import subprocess
import zipfile
import logging
from typing import List

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

# --------------------------------------------------
# APP INIT
# --------------------------------------------------

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # Figma origin = null
    allow_credentials=False,      # MUST be False with "*"
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------
# LOGGING
# --------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("compng")

# --------------------------------------------------
# PNGQUANT
# --------------------------------------------------

def run_pngquant(input_file: str, output_file: str, quality: str = "60-80"):
    cmd = [
        "pngquant",
        f"--quality={quality}",
        "--force",
        "--output", output_file,
        input_file,
    ]
    try:
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(e.output.decode())

# --------------------------------------------------
# ROOT
# --------------------------------------------------

@app.get("/")
async def root():
    return RedirectResponse("/docs")

# --------------------------------------------------
# 1️⃣ ANALYZE ONLY (JSON)
# --------------------------------------------------

@app.post("/compress-analyze")
async def compress_analyze(files: List[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="At least one PNG required")

    if len(files) > 10:
        raise HTTPException(status_code=400, detail="Max 10 files allowed")

    results = []

    with tempfile.TemporaryDirectory() as tmpdir:
        for file in files:
            if not file.filename.lower().endswith(".png"):
                raise HTTPException(status_code=400, detail="Only PNG allowed")

            input_path = os.path.join(tmpdir, file.filename)
            output_path = input_path.replace(".png", "_compressed.png")

            with open(input_path, "wb") as f:
                f.write(await file.read())

            try:
                run_pngquant(input_path, output_path)
            except Exception:
                output_path = input_path

            orig = os.path.getsize(input_path)
            comp = os.path.getsize(output_path)

            used = comp < orig
            final_size = comp if used else orig
            reduction = round((orig - final_size) * 100 / orig, 2) if used else 0.0

            results.append({
                "filename": file.filename,
                "original_size": orig,
                "final_size": final_size,
                "percent_reduction": reduction,
                "used_compressed": used,
            })

    return JSONResponse(results)

# --------------------------------------------------
# 2️⃣ SINGLE FILE DOWNLOAD
# --------------------------------------------------

@app.post("/compress-zip")
async def compress_zip(files: List[UploadFile] = File(...)):
    try:
        if not files:
            raise HTTPException(status_code=400, detail="No files uploaded")

        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = os.path.join(tmpdir, "compressed.zip")

            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                for file in files:
                    if not file.filename.lower().endswith(".png"):
                        raise HTTPException(status_code=400, detail="Only PNG allowed")

                    input_path = os.path.join(tmpdir, file.filename)
                    output_path = input_path.replace(".png", "_compressed.png")

                    with open(input_path, "wb") as f:
                        f.write(await file.read())

                    try:
                        run_pngquant(input_path, output_path)
                    except Exception:
                        output_path = input_path

                    zipf.write(output_path, arcname=file.filename)

            return FileResponse(
                zip_path,
                media_type="application/zip",
                filename="compressed.zip",
            )

    except Exception as e:
        logger.exception("compress-zip failed")
        raise HTTPException(status_code=500, detail=str(e))


# --------------------------------------------------
# 3️⃣ ZIP DOWNLOAD
# --------------------------------------------------

@app.post("/compress-zip")
async def compress_zip(files: List[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="At least one PNG required")

    if len(files) > 10:
        raise HTTPException(status_code=400, detail="Max 10 files allowed")

    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = os.path.join(tmpdir, "compressed.zip")
        stats = []

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file in files:
                if not file.filename.lower().endswith(".png"):
                    raise HTTPException(status_code=400, detail="Only PNG allowed")

                input_path = os.path.join(tmpdir, file.filename)
                output_path = input_path.replace(".png", "_compressed.png")

                with open(input_path, "wb") as f:
                    f.write(await file.read())

                try:
                    run_pngquant(input_path, output_path)
                except Exception:
                    output_path = input_path

                orig = os.path.getsize(input_path)
                comp = os.path.getsize(output_path)

                used = comp < orig
                final_size = comp if used else orig
                reduction = round((orig - final_size) * 100 / orig, 2) if used else 0.0

                zipf.write(output_path, arcname=file.filename)

                stats.append({
                    "filename": file.filename,
                    "original_size": orig,
                    "final_size": final_size,
                    "percent_reduction": reduction,
                    "used_compressed": used,
                })

        return FileResponse(
            zip_path,
            media_type="application/zip",
            filename="compressed.zip",
            headers={
                "X-Compression-Stats": json.dumps(stats)
            }
        )
