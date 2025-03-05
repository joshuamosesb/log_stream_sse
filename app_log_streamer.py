import logging
import os
import asyncio
import traceback
from pathlib import Path
from fastapi import FastAPI, WebSocket, Request
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
from fastapi.templating import Jinja2Templates
import uvicorn
from utils import get_root_path

# Setup logging
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

base_dir = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(Path(base_dir)))

app = FastAPI(root_path="/log-stream", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Start reading the remote log file
root_path = os.getcwd() if os.name == "nt" else get_root_path('v5test2')

log_dir = os.path.join(root_path, 'api_logs')
logfile_path = os.path.join(log_dir, 'app.log')

async def close_websocket(websocket):
    if websocket and websocket.client_state != websocket.CLOSED:
        logger.info(f"Closing websocket")
        await websocket.close()

@app.get("/")
async def read_root(request: Request):
    try:
        context = {"title": "FastAPI Streaming Log Viewer over WebSockets", "log_file": 'app.log'}
        return templates.TemplateResponse("log_stream_http.html", {"request": request, "context": context})
    except Exception:
        logger.error(f"ERROR in request:\n{traceback.format_exc()}")

async def ws_push_log_file(file_path, websocket=None):
    try:
        with open(file_path, 'r') as f:
            logger.info(f'Loaded: {file_path}')
            while True:
                chunk = f.readline()
                if not chunk:
                    if websocket:
                        try:
                            await asyncio.sleep(0.5)
                        except asyncio.CancelledError:
                            logger.error(f"Task for reading log file {file_path} was cancelled.\n{traceback.format_exc()}")
                            return
                        except Exception as e:
                            logger.error(f"Exception in log reading: {e}\n{traceback.format_exc()}")
                            return
                else:
                    if websocket and websocket.client_state != websocket.CLOSED:
                        try:
                            await websocket.send_text(chunk)
                        except asyncio.CancelledError:
                            logger.error(f"Task for reading log file {file_path} was cancelled.\n{traceback.format_exc()}")
                            return
                        except Exception as e:
                            logger.error(f"Exception in log reading: {e}\n{traceback.format_exc()}")
                            return
    except Exception as e:
        logger.error(f"Error in ws_push_log_file: {e}\n{traceback.format_exc()}")
    finally:
        await close_websocket(websocket)

@app.websocket("/ws-log-stream")
async def log_stream(websocket: WebSocket):
    await websocket.accept()
    try:
        logger.info(f'Calling ws: ws_push_log_file {logfile_path}')
        await ws_push_log_file(logfile_path, websocket=websocket)
    except Exception as e:
        logger.error(f"Failed to initialize logger: {str(e)}\n{traceback.format_exc()}")
    finally:
        logger.info(f'Closing websocket')
        await close_websocket(websocket)

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
            logger.debug(f'loaded:{file_path}')
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
                        if http_req is not None and await http_req.is_disconnected():
                            logger.error("http-client disconnected!!!")
                            return
                        yield {"event": "message", "data": line}
                else:
                    await asyncio.sleep(delay)
                    if http_req is not None and await http_req.is_disconnected():
                        logger.error("http-client disconnected while sleeping!!!")
                        return
                    continue
    except FileNotFoundError:
        logger.error(f"Error: Log file not found at {file_path}")
        yield {"event": "message", "data":f"Error: Log file not found at {file_path}"}
        return
    except Exception as e:
        logger.error(f"Error reading log file: {e}\n{traceback.format_exc()}")
        yield {"event": "message", "data":f"Error reading log file: {e}\n{traceback.format_exc()}"}
        return


@app.get('/http-log-stream')
async def run(request: Request):
    logger.debug(f'calling SSE: read_log_file{logfile_path}')
    event_generator = http_push_log_file(logfile_path, http_req=request)
    return EventSourceResponse(event_generator, media_type="text/event-stream")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=7999)
