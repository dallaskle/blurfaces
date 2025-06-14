# blurfaces

## Tool Description

Blurs faces in video with both command-line and web API interfaces.

<table>
<tbody>
<tr>
<td>sample</td>
<td>mode=<b>all</b>, censor-type=<b>gaussianblur</b></td>
</tr>
<tr>
<td><video src='https://user-images.githubusercontent.com/600723/212699288-73a89730-a92b-4136-a340-0e8739fc832d.mp4'/></td>
<td><video src='https://user-images.githubusercontent.com/600723/212761619-ddd63219-f4b1-4b7d-b890-1d66ae190fb0.mp4'/></td>
</tr>
<tr>
<td>mode=<b>one</b>, censor-type=<b>pixelation</b></td>
<td>mode=<b>allexcept</b>, censor-type=<b>facemasking</b></td>
</tr>
<tr>
<td><video src='https://user-images.githubusercontent.com/600723/221906178-4ba56e9e-b143-4f10-9da1-0e9aada87abe.mp4'/></td>
<td><video src='https://user-images.githubusercontent.com/600723/221908350-1d4a7f09-765d-45b0-8293-b1ed3be2a209.mp4'/></td>
</tr>
</tbody>
</table>

## Features

- **Command Line Interface**: Process videos directly from terminal
- **Web API**: RESTful API for programmatic access
- **HTML Demo App**: User-friendly web interface for video processing
- **Three Processing Modes**:
  - **All**: Blur all detected faces
  - **Specific**: Blur only faces matching reference images  
  - **All Except**: Blur all faces except those matching reference images
- **Multiple Censor Types**: Gaussian blur, pixelation, and face masking
- **Two Detection Models**: HOG (faster) and CNN (more accurate)

## Installation

1. Make sure you have Python version 3.10.6 or greater installed

2. Download the tool's repository using the command:

        git clone git@github.com:raviksharma/blurfaces.git

3. Move to the tool's directory and install the tool

        cd blurfaces
        pip install -r requirements.txt

## Usage

### Command Line Interface

```
$ python3 blur_faces.py --help
Usage: blur_faces.py [OPTIONS] IN_VIDEO_FILE

Options:
  --mode [all|one|allexcept]
  --model [hog|cnn]
  --censor-type [gaussianblur|facemasking|pixelation]
  --count INTEGER                 How many times to upsample the image looking
                                  for faces. Higher numbers find smaller
                                  faces.

  --in-face-file TEXT
  --help                          Show this message and exit.
```

**Example:**
```bash
python3 blur_faces.py media/friends.mp4 --mode allexcept --model cnn --censor-type facemasking --in-face-file media/Ross_Geller.jpg
```

### Web API Server

Start the FastAPI server:

```bash
python3 -m uvicorn app:app --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`

### HTML Demo App

Once the server is running, visit `http://localhost:8000` in your browser to access the web interface. The demo app provides:

- **Drag-and-drop file uploads** for videos and reference images
- **Real-time progress tracking** with visual progress bars
- **Three processing modes** with intuitive forms:
  - **Blur All Faces**: Simple video upload with model and censor type selection
  - **Blur Specific Faces**: Upload reference images to blur only matching faces
  - **Blur All Except**: Upload reference images to preserve specific faces while blurring others
- **Automatic job status polling** and download links when processing completes
- **Modern, responsive UI** with clear visual feedback

## API Routes

### Core Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Serves HTML demo app or API info |
| `GET` | `/health` | Health check endpoint |
| `POST` | `/blur/all` | Blur all faces in video |
| `POST` | `/blur/one` | Blur specific faces matching references |
| `POST` | `/blur/allexcept` | Blur all faces except specified ones |
| `GET` | `/status/{job_id}` | Check processing status |
| `GET` | `/download/{job_id}` | Download processed video |
| `DELETE` | `/cleanup/{job_id}` | Clean up job files |

### API Request Parameters

**For all blur endpoints:**
- `video` (file): Video file to process
- `model` (string): `"hog"` (faster) or `"cnn"` (more accurate)  
- `censor_type` (string): `"gaussianblur"`, `"pixelation"`, or `"facemasking"`
- `count` (integer): Upsampling count for face detection (default: 1)

**For `/blur/one` and `/blur/allexcept`:**
- `reference_faces` (files): One or more reference face images

### Example API Usage

**Blur all faces:**
```bash
curl -X POST http://localhost:8000/blur/all \
  -F "video=@video.mp4" \
  -F "model=hog" \
  -F "censor_type=gaussianblur"
```

**Check status:**
```bash
curl http://localhost:8000/status/{job_id}
```

**Download result:**
```bash
curl -O http://localhost:8000/download/{job_id}
```

### Response Format

**Job submission response:**
```json
{
  "job_id": "uuid-string",
  "status": "accepted", 
  "check_status_url": "/status/{job_id}"
}
```

**Status check responses:**
```json
// Processing
{
  "status": "processing",
  "progress": 45
}

// Completed
{
  "status": "completed",
  "progress": 100,
  "output_file": "processed/job-id.mp4",
  "download_url": "/download/{job_id}"
}

// Failed
{
  "status": "failed", 
  "error": "Error message"
}
```

## How the HTML Demo App Works

The web interface (`static/index.html`) provides a user-friendly way to interact with the API:

1. **File Upload**: Users select video files and reference images through HTML file inputs
2. **Form Submission**: JavaScript handles form submission and creates FormData objects
3. **API Communication**: Forms POST to corresponding API endpoints (`/blur/all`, `/blur/one`, `/blur/allexcept`)
4. **Asynchronous Processing**: Server returns job ID immediately and processes video in background
5. **Status Polling**: JavaScript polls `/status/{job_id}` every second to update progress
6. **Progress Display**: Visual progress bars show processing percentage
7. **Download Ready**: When complete, download link appears automatically
8. **Error Handling**: Failed jobs display error messages in the interface

The app uses modern web technologies:
- **Responsive CSS**: Clean, mobile-friendly design
- **Vanilla JavaScript**: No external dependencies
- **Fetch API**: Modern HTTP requests
- **Real-time Updates**: Automatic status polling
- **File Validation**: Client-side file type checking

## Additional Information

- Originally developed for [Bellingcat Oct 2022 Hackathon](https://www.bellingcat.com/resources/2022/10/06/automated-map-searches-scam-busting-tools-and-twitter-search-translations-here-are-the-results-of-bellingcats-second-hackathon/)
- Uses [face_recognition](https://github.com/ageitgey/face_recognition) for face detection
- Uses [ffmpeg](https://ffmpeg.org/) for audio and video processing  
- Uses [FastAPI](https://fastapi.tiangolo.com/) for the web API
- Tool is not perfect; should be used with other manual editing before final publish
- Video processing is asynchronous with background task queuing
- Processed videos include original audio tracks when present
- See `API_DOCS.md` for detailed API documentation
- See `client_example.py` for Python client implementation

### Next Steps
- Smooth face_locations (fixes failure in detecting odd frames)
- Detect scene change and use it to reset face_locations[]
- Choose num_jitters
- Add batch processing capabilities
- Implement user authentication for production deployments
