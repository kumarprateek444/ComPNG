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
    BackgroundTasks,
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
    allow_credentials=False,      # MUST be False with "*"
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================================================
# LOGGING
# ==================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("compng")

# ==================================================
# PNGQUANT HELPER
# ==================================================

def run_pngquant(input_file: str, output_file: str, quality: str = "60-80"):
    cmd = [
        "pngquant",
        f"--quality={quality}",
        "--force",
        "--output",
        output_file,
        input_file,
    ]
    try:
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(e.output.decode())

# ==================================================
# ROOT
# ==================================================

@app.get("/")
async def root():
    return RedirectResponse("/docs")

# ==================================================
# 1️⃣ ANALYZE ONLY (NO DOWNLOAD)
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

# ==================================================
# 2️⃣ SINGLE FILE DOWNLOAD
# ==================================================

@app.post("/compress-file")
async def compress_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...)
):
    if not file.filename.lower().endswith(".png"):
        raise HTTPException(status_code=400, detail="Only PNG allowed")

    tmpdir = tempfile.mkdtemp()
    input_path = os.path.join(tmpdir, file.filename)
    output_path = input_path.replace(".png", "_compressed.png")

    with open(input_path, "wb") as f:
        f.write(await file.read())

    try:
        run_pngquant(input_path, output_path)
        final_path = output_path
    except Exception:
        final_path = input_path

    background_tasks.add_task(
        lambda: shutil.rmtree(tmpdir, ignore_errors=True)
    )

    return FileResponse(
        final_path,
        media_type="image/png",
        filename=file.filename,
    )

# ==================================================
# 3️⃣ MULTIPLE FILES → ZIP DOWNLOAD
# ==================================================

@app.post("/compress-zip")
async def compress_zip(
    background_tasks: BackgroundTasks,
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

                # ✅ UNIQUE FILE NAMES (CRITICAL FIX)
                safe_name = f"{index}_{file.filename}"
                input_path = os.path.join(tmpdir, safe_name)
                output_path = os.path.join(
                    tmpdir,
                    f"{index}_compressed.png"
                )

                with open(input_path, "wb") as f:
                    f.write(await file.read())

                try:
                    run_pngquant(input_path, output_path)
                    final_path = output_path
                except Exception:
                    final_path = input_path

                orig = os.path.getsize(input_path)
                comp = os.path.getsize(final_path)

                used = comp < orig
                final_size = comp if used else orig
                reduction = round((orig - final_size) * 100 / orig, 2) if used else 0.0

                # ZIP keeps ORIGINAL filename (UI consistency)
                zipf.write(final_path, arcname=file.filename)

                stats.append({
                    "filename": file.filename,
                    "original_size": orig,
                    "final_size": final_size,
                    "percent_reduction": reduction,
                    "used_compressed": used,
                })

        background_tasks.add_task(
            lambda: shutil.rmtree(tmpdir, ignore_errors=True)
        )

        return FileResponse(
            zip_path,
            media_type="application/zip",
            filename="compressed.zip",
            headers={
                "X-Compression-Stats": json.dumps(stats)
            },
        )

    except Exception as e:
        shutil.rmtree(tmpdir, ignore_errors=True)
        logger.exception("ZIP compression failed")
        raise HTTPException(status_code=500, detail=str(e))

