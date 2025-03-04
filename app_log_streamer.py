from pathlib import Path
import os
import time
from fastapi import FastAPI, WebSocket, Request
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from fastapi.templating import Jinja2Templates
import asyncio
import uvicorn
from utils import get_root_path
import traceback


base_dir = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(Path(base_dir)))

if os.name == "nt":
    app = FastAPI(root_path="/log-stream", docs_url=None, redoc_url=None)
if os.name == "posix":
    app = FastAPI(root_path="/log-stream", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Start reading the remote log file
if os.name == "nt":
    root_path = os.getcwd()
else:
    root_path = get_root_path('v5test2')
# Define log path
log_dir = os.path.join(root_path, 'api_logs')
logfile_path = os.path.join(log_dir, 'app.log')

@app.get("/")
async def read_root(request: Request):
    try:
        # return {"message": "Welcome to the FastAPI application to stream app.log to the websocket!"}
        context = {"title": "FastAPI Streaming Log Viewer over WebSockets", "log_file": 'app.log'}
        return templates.TemplateResponse("log_stream_http.html", {"request": request, "context": context})
    except:
        print(f"ERROR in request: \n********************************\n{traceback.format_exc()}")

# sh not available in "nt"
# from sh import tail
# async def stream_log_tail(file_path, request):
#     for line in tail("-f", file_path, _iter=True):
#         if await request.is_disconnected():
#             print("client disconnected!!!")
#             break
#         yield line
#         time.sleep(0.5)

# Function to read log file in chunks
async def ws_push_log_file(file_path, websocket=None):
    with open(file_path, 'r') as f:
        print(f'loaded:{file_path}')
        while True:
            chunk = f.readline()  # Read a chunk at a time
            if not chunk:
                if websocket:
                    try:
                        await asyncio.sleep(0.5)  # Wait for new data
                        await websocket.send_text(chunk)
                    except asyncio.CancelledError:
                        print(f"Task for reading log file {file_path} was cancelled.\n#############\n{traceback.format_exc()}")
                        # You can add cleanup code here if needed.
                    except Exception as e:
                        print(f'Exception in log reading: {e}\n\n@@@@@@@@@@@@@@@@@n{traceback.format_exc()}')
            else:
                continue

@app.websocket("/ws-log-stream")
async def log_stream(websocket: WebSocket):

    await websocket.accept()

    try:
        print(f'calling ws: ws_push_log_file{logfile_path}')
        asyncio.create_task(ws_push_log_file(logfile_path, websocket=websocket)) 
    except Exception as e:
        print(f"Failed to initialize logger: {str(e)}\n****************\n{traceback.format_exc()}")
    finally:
        print(f'#######################closing websocket#####################')
        await websocket.close()


async def http_push_log_file(file_path, chunk_size=1024, delay=0.5, http_req=None):
    """
    Reads a log file in chunks, yielding new content as it's written.

    Args:
        file_path (str): The path to the log file.
        chunk_size (int): The size of each chunk to read (in bytes). Defaults to 1024 (1KB).
        delay (float): The delay (in seconds) between checks for new data. Defaults to 0.5 seconds.

    Yields:
        str: A chunk of new data from the log file.
    """
    try:
        file_size = 0
        with open(file_path, 'r') as log_file:
            print(f'loaded:{file_path}')
            while True:
                current_file_size = os.path.getsize(file_path)
                if current_file_size > file_size:
                    log_file.seek(file_size)
                    # Read the new chunk
                    chunk = log_file.read(chunk_size)
                    file_size = log_file.tell()
                    # process the chunk line by line
                    lines = chunk.splitlines(keepends=True)
                    for line in lines:
                        if await http_req.is_disconnected():
                            print("http-client disconnected!!!")
                            break
                        yield {"event": "message", "data": line}
                else:
                    time.sleep(delay)
                    continue
    except FileNotFoundError:
        print(f"Error: Log file not found at {file_path}")
        yield {"event": "message", "data":f"Error: Log file not found at {file_path}"}
        return
    except Exception as e:
        print(f"Error reading log file: {e}\n{traceback.format_exc()}")
        yield {"event": "message", "data":f"Error reading log file: {e}\n{traceback.format_exc()}"}
        return


@app.get('/http-log-stream')
async def run(request: Request):
    print(f'calling ws: read_log_file{logfile_path}')
    event_generator = http_push_log_file(logfile_path, http_req=request)
    return EventSourceResponse(event_generator, media_type="text/event-stream")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=9000)