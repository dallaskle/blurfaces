from fastapi import FastAPI, File, UploadFile, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from typing import List, Optional
import os
import uuid
import tempfile
import shutil
from pathlib import Path
import asyncio
from datetime import datetime

# Import the blur faces functionality
from blur_faces import get_video_properties, get_face_encoding, get_blurred_face, decode_fourcc, has_audio
import cv2
import face_recognition
import ffmpeg
import numpy as np
from tqdm import trange

app = FastAPI(title="BlurFaces API", version="1.0.0")

# Create directories for uploads and processed videos
UPLOAD_DIR = Path("uploads")
PROCESSED_DIR = Path("processed")
STATIC_DIR = Path("static")
UPLOAD_DIR.mkdir(exist_ok=True)
PROCESSED_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)

# Mount static files for processed videos
app.mount("/processed", StaticFiles(directory="processed"), name="processed")

# Store job status
job_status = {}

@app.get("/")
async def root():
    # Serve the HTML interface if it exists
    html_path = STATIC_DIR / "index.html"
    if html_path.exists():
        return FileResponse(html_path)
    return {
        "message": "Welcome to BlurFaces API",
        "endpoints": {
            "/blur/all": "Blur all faces in video",
            "/blur/one": "Blur specific faces in video (requires reference images)",
            "/blur/allexcept": "Blur all faces except specific ones (requires reference images)",
            "/status/{job_id}": "Check processing status",
            "/download/{job_id}": "Download processed video"
        }
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

async def process_video(
    job_id: str,
    video_path: str,
    mode: str,
    model: str = "hog",
    censor_type: str = "gaussianblur",
    count: int = 1,
    reference_faces: List[str] = None
):
    """Background task to process video"""
    try:
        job_status[job_id] = {"status": "processing", "progress": 0}
        
        # Open video
        video_capture = cv2.VideoCapture(video_path)
        width, height, length, fps, fourcc, codec = get_video_properties(video_capture)
        
        # Output path
        output_path = PROCESSED_DIR / f"{job_id}.mp4"
        temp_video_path = PROCESSED_DIR / f"{job_id}_temp.mp4"
        
        # Create video writer
        video_out = cv2.VideoWriter(
            str(temp_video_path), int(fourcc), fps, (width, height)
        )
        
        # Get reference encodings if needed
        reference_encodings = []
        if mode in ["one", "allexcept"] and reference_faces:
            for ref_face_path in reference_faces:
                try:
                    encoding = get_face_encoding(ref_face_path)
                    reference_encodings.append(encoding)
                except Exception as e:
                    print(f"Error loading reference face {ref_face_path}: {e}")
        
        # Process frames
        for i in range(length + 1):
            ret, frame = video_capture.read()
            if not ret:
                break
            
            # Update progress
            progress = int((i / length) * 100)
            job_status[job_id]["progress"] = progress
            
            # Detect faces
            face_locations = face_recognition.face_locations(
                frame, number_of_times_to_upsample=count, model=model
            )
            
            if mode == "all":
                # Blur all faces
                for face_location in face_locations:
                    frame = get_blurred_face(frame, censor_type, face_location)
            
            elif mode == "one" and reference_encodings:
                # Blur only matching faces
                face_encodings = face_recognition.face_encodings(frame, face_locations)
                for face_encoding, face_location in zip(face_encodings, face_locations):
                    matches = face_recognition.compare_faces(reference_encodings, face_encoding)
                    if any(matches):
                        frame = get_blurred_face(frame, censor_type, face_location)
            
            elif mode == "allexcept" and reference_encodings:
                # Blur all except matching faces
                face_encodings = face_recognition.face_encodings(frame, face_locations)
                for face_encoding, face_location in zip(face_encodings, face_locations):
                    matches = face_recognition.compare_faces(reference_encodings, face_encoding)
                    if not any(matches):
                        frame = get_blurred_face(frame, censor_type, face_location)
            
            video_out.write(frame)
        
        # Release resources
        video_capture.release()
        video_out.release()
        cv2.destroyAllWindows()
        
        # Add audio if present
        if has_audio(video_path):
            in_av = ffmpeg.input(video_path)
            blurred_video = ffmpeg.input(str(temp_video_path))
            stream = ffmpeg.output(
                blurred_video, in_av.audio, str(output_path)
            ).overwrite_output()
            ffmpeg.run(stream, quiet=True)
            os.remove(temp_video_path)
        else:
            shutil.move(str(temp_video_path), str(output_path))
        
        # Update job status
        job_status[job_id] = {
            "status": "completed",
            "progress": 100,
            "output_file": str(output_path),
            "download_url": f"/download/{job_id}"
        }
        
    except Exception as e:
        job_status[job_id] = {
            "status": "failed",
            "error": str(e)
        }
        raise
    finally:
        # Clean up uploaded files
        if os.path.exists(video_path):
            os.remove(video_path)
        if reference_faces:
            for ref_path in reference_faces:
                if os.path.exists(ref_path):
                    os.remove(ref_path)

@app.post("/blur/all")
async def blur_all_faces(
    background_tasks: BackgroundTasks,
    video: UploadFile = File(...),
    model: str = Form("hog"),
    censor_type: str = Form("gaussianblur"),
    count: int = Form(1)
):
    """Blur all faces in the uploaded video"""
    
    # Validate inputs
    if model not in ["hog", "cnn"]:
        raise HTTPException(400, "Model must be 'hog' or 'cnn'")
    if censor_type not in ["gaussianblur", "facemasking", "pixelation"]:
        raise HTTPException(400, "Invalid censor type")
    
    # Generate job ID
    job_id = str(uuid.uuid4())
    
    # Save uploaded video
    video_path = UPLOAD_DIR / f"{job_id}_{video.filename}"
    with open(video_path, "wb") as f:
        content = await video.read()
        f.write(content)
    
    # Start background processing
    background_tasks.add_task(
        process_video,
        job_id=job_id,
        video_path=str(video_path),
        mode="all",
        model=model,
        censor_type=censor_type,
        count=count
    )
    
    return {
        "job_id": job_id,
        "status": "accepted",
        "check_status_url": f"/status/{job_id}"
    }

@app.post("/blur/one")
async def blur_specific_faces(
    background_tasks: BackgroundTasks,
    video: UploadFile = File(...),
    reference_faces: List[UploadFile] = File(...),
    model: str = Form("hog"),
    censor_type: str = Form("gaussianblur"),
    count: int = Form(1)
):
    """Blur only specific faces that match reference images"""
    
    if not reference_faces:
        raise HTTPException(400, "At least one reference face image is required")
    
    # Validate inputs
    if model not in ["hog", "cnn"]:
        raise HTTPException(400, "Model must be 'hog' or 'cnn'")
    if censor_type not in ["gaussianblur", "facemasking", "pixelation"]:
        raise HTTPException(400, "Invalid censor type")
    
    # Generate job ID
    job_id = str(uuid.uuid4())
    
    # Save uploaded video
    video_path = UPLOAD_DIR / f"{job_id}_{video.filename}"
    with open(video_path, "wb") as f:
        content = await video.read()
        f.write(content)
    
    # Save reference faces
    ref_paths = []
    for i, ref_face in enumerate(reference_faces):
        ref_path = UPLOAD_DIR / f"{job_id}_ref_{i}_{ref_face.filename}"
        with open(ref_path, "wb") as f:
            content = await ref_face.read()
            f.write(content)
        ref_paths.append(str(ref_path))
    
    # Start background processing
    background_tasks.add_task(
        process_video,
        job_id=job_id,
        video_path=str(video_path),
        mode="one",
        model=model,
        censor_type=censor_type,
        count=count,
        reference_faces=ref_paths
    )
    
    return {
        "job_id": job_id,
        "status": "accepted",
        "check_status_url": f"/status/{job_id}"
    }

@app.post("/blur/allexcept")
async def blur_all_except_specific_faces(
    background_tasks: BackgroundTasks,
    video: UploadFile = File(...),
    reference_faces: List[UploadFile] = File(...),
    model: str = Form("hog"),
    censor_type: str = Form("gaussianblur"),
    count: int = Form(1)
):
    """Blur all faces except those that match reference images"""
    
    if not reference_faces:
        raise HTTPException(400, "At least one reference face image is required")
    
    # Validate inputs
    if model not in ["hog", "cnn"]:
        raise HTTPException(400, "Model must be 'hog' or 'cnn'")
    if censor_type not in ["gaussianblur", "facemasking", "pixelation"]:
        raise HTTPException(400, "Invalid censor type")
    
    # Generate job ID
    job_id = str(uuid.uuid4())
    
    # Save uploaded video
    video_path = UPLOAD_DIR / f"{job_id}_{video.filename}"
    with open(video_path, "wb") as f:
        content = await video.read()
        f.write(content)
    
    # Save reference faces
    ref_paths = []
    for i, ref_face in enumerate(reference_faces):
        ref_path = UPLOAD_DIR / f"{job_id}_ref_{i}_{ref_face.filename}"
        with open(ref_path, "wb") as f:
            content = await ref_face.read()
            f.write(content)
        ref_paths.append(str(ref_path))
    
    # Start background processing
    background_tasks.add_task(
        process_video,
        job_id=job_id,
        video_path=str(video_path),
        mode="allexcept",
        model=model,
        censor_type=censor_type,
        count=count,
        reference_faces=ref_paths
    )
    
    return {
        "job_id": job_id,
        "status": "accepted",
        "check_status_url": f"/status/{job_id}"
    }

@app.get("/status/{job_id}")
async def get_job_status(job_id: str):
    """Check the status of a video processing job"""
    
    if job_id not in job_status:
        raise HTTPException(404, "Job not found")
    
    return job_status[job_id]

@app.get("/download/{job_id}")
async def download_processed_video(job_id: str):
    """Download the processed video"""
    
    if job_id not in job_status:
        raise HTTPException(404, "Job not found")
    
    status = job_status[job_id]
    if status["status"] != "completed":
        raise HTTPException(400, f"Job is {status['status']}, not completed")
    
    output_path = Path(status["output_file"])
    if not output_path.exists():
        raise HTTPException(404, "Processed video file not found")
    
    return FileResponse(
        output_path,
        media_type="video/mp4",
        filename=f"blurred_{job_id}.mp4"
    )

@app.delete("/cleanup/{job_id}")
async def cleanup_job(job_id: str):
    """Clean up processed video and job data"""
    
    if job_id not in job_status:
        raise HTTPException(404, "Job not found")
    
    # Remove processed video
    output_path = PROCESSED_DIR / f"{job_id}.mp4"
    if output_path.exists():
        os.remove(output_path)
    
    # Remove job status
    del job_status[job_id]
    
    return {"message": "Job cleaned up successfully"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 