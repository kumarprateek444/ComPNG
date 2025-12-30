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
    allow_credentials=False,
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

def run_pngquant(input_file: str, output_file: str, quality="60-80"):
    cmd = [
        "pngquant",
        f"--quality={quality}",
        "--force",
        "--output", output_file,
        input_file,
    ]
    subprocess.check_output(cmd, stderr=subprocess.STDOUT)

# --------------------------------------------------
# ROOT
# --------------------------------------------------

@app.get("/")
async def root():
    return RedirectResponse("/docs")

# --------------------------------------------------
# ANALYZE ONLY
# --------------------------------------------------

@app.post("/compress-analyze")
async def compress_analyze(files: List[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="At least one PNG required")

    results = []

    with tempfile.TemporaryDirectory() as tmpdir:
        for idx, file in enumerate(files):
            if not file.filename.lower().endswith(".png"):
                raise HTTPException(status_code=400, detail="Only PNG allowed")

            raw_bytes = await file.read()  # 🔥 read ONCE
            if not raw_bytes:
                raise HTTPException(status_code=400, detail="Empty file")

            input_path = os.path.join(tmpdir, f"{idx}_{file.filename}")
            output_path = input_path.replace(".png", "_compressed.png")

            with open(input_path, "wb") as f:
                f.write(raw_bytes)

            try:
                run_pngquant(input_path, output_path)
                compressed = True
            except Exception as e:
                logger.warning(f"pngquant failed for {file.filename}: {e}")
                output_path = input_path
                compressed = False

            orig = os.path.getsize(input_path)
            final = os.path.getsize(output_path)

            reduction = round((orig - final) * 100 / orig, 2) if compressed else 0.0

            results.append({
                "filename": file.filename,
                "original_size": orig,
                "final_size": final,
                "percent_reduction": reduction,
                "used_compressed": compressed,
            })

    return JSONResponse(results)

# --------------------------------------------------
# ZIP EXPORT
# --------------------------------------------------

@app.post("/compress-zip")
async def compress_zip(files: List[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="At least one PNG required")

    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = os.path.join(tmpdir, "compressed.zip")
        stats = []

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for idx, file in enumerate(files):
                if not file.filename.lower().endswith(".png"):
                    raise HTTPException(status_code=400, detail="Only PNG allowed")

                raw_bytes = await file.read()  # 🔥 read ONCE
                if not raw_bytes:
                    raise HTTPException(status_code=400, detail="Empty file")

                input_path = os.path.join(tmpdir, f"{idx}_{file.filename}")
                output_path = input_path.replace(".png", "_compressed.png")

                with open(input_path, "wb") as f:
                    f.write(raw_bytes)

                try:
                    run_pngquant(input_path, output_path)
                    final_path = output_path
                    used = True
                except Exception as e:
                    logger.warning(f"pngquant failed for {file.filename}: {e}")
                    final_path = input_path
                    used = False

                orig = os.path.getsize(input_path)
                final = os.path.getsize(final_path)
                reduction = round((orig - final) * 100 / orig, 2) if used else 0.0

                zipf.write(final_path, arcname=file.filename)

                stats.append({
                    "filename": file.filename,
                    "original_size": orig,
                    "final_size": final,
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
