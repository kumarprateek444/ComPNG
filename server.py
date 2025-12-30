import logging
import os
import tempfile
import subprocess
import zipfile
import json
from typing import List

from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.middleware.cors import CORSMiddleware

# --------------------------------------------------
# APP INITIALIZATION (ONLY ONCE)
# --------------------------------------------------

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # required for Figma (origin = null)
    allow_credentials=False,  # 🔥 MUST be False with wildcard
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------
# LOGGING
# --------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
        raise Exception(f"pngquant failed: {e.output.decode()}")

# --------------------------------------------------
# ROOT
# --------------------------------------------------

@app.get("/")
async def root():
    return RedirectResponse("/docs")

# --------------------------------------------------
# CORS PREFLIGHT (CRITICAL)
# --------------------------------------------------

@app.options("/compress-download")
async def options_compress_download(request: Request):
    return Response(status_code=204)

# --------------------------------------------------
# MAIN ENDPOINT
# --------------------------------------------------

@app.post("/compress-download")
async def compress_and_download(files: List[UploadFile] = File(...)):

    if len(files) == 0:
        raise HTTPException(status_code=400, detail="At least one file required")

    if len(files) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 files allowed")

    temp_dir = tempfile.mkdtemp()
    output_files = []

    try:
        for file in files:
            if not file.filename.lower().endswith(".png"):
                raise HTTPException(
                    status_code=400,
                    detail=f"Only PNG allowed. Invalid file: {file.filename}"
                )

            logger.info(f"Compressing for download: {file.filename}")

            input_path = os.path.join(temp_dir, file.filename)
            compressed_path = input_path.replace(".png", "_compressed.png")

            with open(input_path, "wb") as f:
                f.write(await file.read())

            try:
                run_pngquant(input_path, compressed_path)
            except Exception:
                compressed_path = input_path

            orig_size = os.path.getsize(input_path)
            comp_size = os.path.getsize(compressed_path)

            if comp_size < orig_size:
                final_path = compressed_path
                final_size = comp_size
                percent_reduction = round((orig_size - comp_size) * 100 / orig_size, 2)
                used_compressed = True
            else:
                final_path = input_path
                final_size = orig_size
                percent_reduction = 0.0
                used_compressed = False

            output_files.append({
                "path": final_path,
                "filename": file.filename,
                "stats": {
                    "filename": file.filename,
                    "original_size": orig_size,
                    "final_size": final_size,
                    "percent_reduction": percent_reduction,
                    "used_compressed": used_compressed,
                },
            })

        stats_json = json.dumps([item["stats"] for item in output_files])

        # SINGLE FILE
        if len(output_files) == 1:
            f = output_files[0]
            return FileResponse(
                f["path"],
                media_type="image/png",
                filename=f["filename"],
                headers={"X-Compression-Stats": stats_json},
            )

        # MULTIPLE FILES → ZIP
        zip_name = "compressed.zip"
        zip_path = os.path.join(temp_dir, zip_name)

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for item in output_files:
                zipf.write(item["path"], arcname=item["filename"])

        return FileResponse(
            zip_path,
            media_type="application/zip",
            filename=zip_name,
            headers={"X-Compression-Stats": stats_json},
        )

    finally:
        pass
