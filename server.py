import os
import json
import shutil
import tempfile
import subprocess
import zipfile
import logging
from typing import List

from fastapi import (
    FastAPI,
    UploadFile,
    File,
    HTTPException,
)
from fastapi.responses import (
    JSONResponse,
    FileResponse,
    RedirectResponse,
)
from fastapi.middleware.cors import CORSMiddleware

# ==================================================
# APP INITIALIZATION
# ==================================================

app = FastAPI(title="ComPNG API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # Figma origin = null
    allow_credentials=False,      # MUST be False with wildcard
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================================================
# LOGGING
# ==================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("compng")

# ==================================================
# PNGQUANT WRAPPER (NEVER CRASHES)
# ==================================================

def run_pngquant_safe(input_file: str, output_file: str) -> bool:
    """
    Tries to compress using pngquant.
    Returns True if compressed file is produced.
    Returns False if pngquant fails for any reason.
    NEVER raises.
    """
    cmd = [
        "pngquant",
        "--quality=60-80",
        "--force",
        "--output",
        output_file,
        input_file,
    ]

    try:
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        if os.path.exists(output_file):
            return True
        return False
    except Exception as e:
        logger.warning(
            f"pngquant failed for {os.path.basename(input_file)}: {e}"
        )
        return False

# ==================================================
# ROOT
# ==================================================

@app.get("/")
async def root():
    return RedirectResponse("/docs")

# ==================================================
# 1️⃣ ANALYZE ONLY (JSON RESPONSE)
# ==================================================

@app.post("/compress-analyze")
async def compress_analyze(
    files: List[UploadFile] = File(...)
):
    if not files:
        raise HTTPException(status_code=400, detail="At least one PNG required")

    if len(files) > 10:
        raise HTTPException(status_code=400, detail="Max 10 files allowed")

    results = []

    with tempfile.TemporaryDirectory() as tmpdir:
        for index, file in enumerate(files):
            if not file.filename.lower().endswith(".png"):
                raise HTTPException(status_code=400, detail="Only PNG allowed")

            raw_bytes = await file.read()
            if not raw_bytes:
                raise HTTPException(status_code=400, detail="Empty PNG file")

            input_path = os.path.join(tmpdir, f"{index}_input.png")
            output_path = os.path.join(tmpdir, f"{index}_compressed.png")

            with open(input_path, "wb") as f:
                f.write(raw_bytes)

            compressed = run_pngquant_safe(input_path, output_path)

            if compressed:
                final_path = output_path
            else:
                final_path = input_path

            orig_size = os.path.getsize(input_path)
            final_size = os.path.getsize(final_path)

            reduction = (
                round((orig_size - final_size) * 100 / orig_size, 2)
                if compressed
                else 0.0
            )

            results.append({
                "filename": file.filename,
                "original_size": orig_size,
                "final_size": final_size,
                "percent_reduction": reduction,
                "used_compressed": compressed,
            })

    return JSONResponse(results)

# ==================================================
# 2️⃣ SINGLE FILE DOWNLOAD
# ==================================================

@app.post("/compress-file")
async def compress_file(
    file: UploadFile = File(...)
):
    if not file.filename.lower().endswith(".png"):
        raise HTTPException(status_code=400, detail="Only PNG allowed")

    tmpdir = tempfile.mkdtemp()

    try:
        raw_bytes = await file.read()
        if not raw_bytes:
            raise HTTPException(status_code=400, detail="Empty PNG file")

        input_path = os.path.join(tmpdir, "input.png")
        output_path = os.path.join(tmpdir, "compressed.png")

        with open(input_path, "wb") as f:
            f.write(raw_bytes)

        compressed = run_pngquant_safe(input_path, output_path)

        final_path = output_path if compressed else input_path

        return FileResponse(
            final_path,
            media_type="image/png",
            filename=file.filename,
        )

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

# ==================================================
# 3️⃣ MULTIPLE FILES → ZIP DOWNLOAD
# ==================================================

@app.post("/compress-zip")
async def compress_zip(
    files: List[UploadFile] = File(...)
):
    if not files:
        raise HTTPException(status_code=400, detail="At least one PNG required")

    if len(files) > 10:
        raise HTTPException(status_code=400, detail="Max 10 files allowed")

    tmpdir = tempfile.mkdtemp()
    zip_path = os.path.join(tmpdir, "compressed.zip")
    stats = []

    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for index, file in enumerate(files):
                if not file.filename.lower().endswith(".png"):
                    raise HTTPException(status_code=400, detail="Only PNG allowed")

                raw_bytes = await file.read()
                if not raw_bytes:
                    continue  # skip empty files safely

                input_path = os.path.join(tmpdir, f"{index}_input.png")
                output_path = os.path.join(tmpdir, f"{index}_compressed.png")

                with open(input_path, "wb") as f:
                    f.write(raw_bytes)

                compressed = run_pngquant_safe(input_path, output_path)

                final_path = output_path if compressed else input_path

                orig_size = os.path.getsize(input_path)
                final_size = os.path.getsize(final_path)

                reduction = (
                    round((orig_size - final_size) * 100 / orig_size, 2)
                    if compressed
                    else 0.0
                )

                zipf.write(final_path, arcname=file.filename)

                stats.append({
                    "filename": file.filename,
                    "original_size": orig_size,
                    "final_size": final_size,
                    "percent_reduction": reduction,
                    "used_compressed": compressed,
                })

        return FileResponse(
            zip_path,
            media_type="application/zip",
            filename="compressed.zip",
            headers={
                "X-Compression-Stats": json.dumps(stats)
            },
        )

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
