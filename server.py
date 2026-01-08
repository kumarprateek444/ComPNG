import os
import tempfile
import subprocess
import logging
import zipfile
from typing import List

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse


# --------------------------------------------------
# APP INIT
# --------------------------------------------------

app = FastAPI()
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # required for Figma (origin = null)
    allow_credentials=False,    # MUST be False when using "*"
    allow_methods=["*"],        # allows POST, OPTIONS, etc.
    allow_headers=["*"],        # allows multipart/form-data
)

from fastapi.responses import RedirectResponse

@app.get("/")
async def root():
    return RedirectResponse(url="/docs")


# --------------------------------------------------
# LOGGING
# --------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("compress-analyze")

# --------------------------------------------------
# PNGQUANT HELPER
# --------------------------------------------------

def run_pngquant(input_path: str, output_path: str, quality: str = "60-80"):
    cmd = [
        "pngquant",
        f"--quality={quality}",
        "--force",
        "--output", output_path,
        input_path,
    ]

    try:
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(e.output.decode())

# --------------------------------------------------
# ANALYZE ENDPOINT (JSON ONLY)
# --------------------------------------------------

@app.post("/compress-analyze")
async def compress_analyze(
    files: List[UploadFile] = File(...)
):
    # ---------- validation ----------
    if not files:
        raise HTTPException(status_code=400, detail="At least one PNG file required")

    if len(files) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 files allowed")

    results = []

    # ---------- temp workspace ----------
    with tempfile.TemporaryDirectory() as tmpdir:

        for file in files:
            if not file.filename.lower().endswith(".png"):
                raise HTTPException(
                    status_code=400,
                    detail=f"Only PNG allowed: {file.filename}"
                )

            input_path = os.path.join(tmpdir, file.filename)
            output_path = input_path.replace(".png", "_compressed.png")

            # save upload
            with open(input_path, "wb") as f:
                f.write(await file.read())

            # compress attempt
            try:
                run_pngquant(input_path, output_path)
            except Exception as e:
                logger.warning("pngquant failed for %s, using original", file.filename)
                output_path = input_path

            # stats
            original_size = os.path.getsize(input_path)
            compressed_size = os.path.getsize(output_path)

            used_compressed = compressed_size < original_size
            final_size = compressed_size if used_compressed else original_size

            percent_reduction = (
                round((original_size - final_size) * 100 / original_size, 2)
                if used_compressed else 0.0
            )

            results.append({
                "filename": file.filename,
                "original_size": original_size,
                "final_size": final_size,
                "percent_reduction": percent_reduction,
                "used_compressed": used_compressed,
            })

    return JSONResponse(results)

# --------------------------------------------------
# SINGLE FILE DOWNLOAD
# --------------------------------------------------

@app.post("/compress-file")
async def compress_file(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".png"):
        raise HTTPException(status_code=400, detail="Only PNG allowed")

    # create temp files (DO NOT auto-delete)
    input_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    output_path = input_tmp.name.replace(".png", "_compressed.png")

    try:
        # save upload
        input_tmp.write(await file.read())
        input_tmp.close()

        # try compression
        try:
            run_pngquant(input_tmp.name, output_path)
        except Exception:
            output_path = input_tmp.name

        # choose smaller file
        orig_size = os.path.getsize(input_tmp.name)
        final_size = os.path.getsize(output_path)

        final_path = output_path if final_size < orig_size else input_tmp.name

        return FileResponse(
            final_path,
            media_type="image/png",
            filename=file.filename
        )

    except Exception as e:
        logger.exception("compress-file failed")
        raise HTTPException(status_code=500, detail=str(e))


# --------------------------------------------------
# MULTIPLE FILE DOWNLOAD
# --------------------------------------------------

@app.post("/compress-zip")
async def compress_zip(files: List[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="At least one PNG required")

    if len(files) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 files allowed")

    # Create a persistent temp ZIP file
    zip_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    zip_path = zip_tmp.name
    zip_tmp.close()

    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file in files:
                if not file.filename.lower().endswith(".png"):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Only PNG allowed: {file.filename}"
                    )

                # temp input
                input_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
                input_tmp.write(await file.read())
                input_tmp.close()

                output_path = input_tmp.name.replace(".png", "_compressed.png")

                try:
                    run_pngquant(input_tmp.name, output_path)
                except Exception:
                    output_path = input_tmp.name

                # choose smaller
                orig_size = os.path.getsize(input_tmp.name)
                final_size = os.path.getsize(output_path)
                final_path = output_path if final_size < orig_size else input_tmp.name

                # add to zip with ORIGINAL filename
                zipf.write(final_path, arcname=file.filename)

        return FileResponse(
            zip_path,
            media_type="application/zip",
            filename="compressed.zip"
        )

    except Exception as e:
        logger.exception("compress-zip failed")
        raise HTTPException(status_code=500, detail=str(e))

